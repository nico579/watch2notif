package io.github.nico579.watch2notif;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CancellationException;

/** GitHub release updates: no provider tokens, bounded HTTPS, digest and APK identity checks. */
final class ReleaseUpdates {
    static final String REPOSITORY = "https://github.com/nico579/watch2notif";
    static final String LATEST = "https://api.github.com/repos/nico579/watch2notif/releases/latest";
    static final String APK_NAME = "watch2notif-android.apk";
    static final long MAX_APK = 64L * 1024 * 1024;
    interface Connections { HttpURLConnection open(URL url) throws IOException; }
    interface Progress { void update(long done, long total); }
    static final class Failure extends IOException {
        final int message;
        Failure(int message) { super("Update failed"); this.message = message; }
    }
    static final class Release {
        final String version, url, sha256, checksums;
        final int versionCode;
        final long size;
        Release(String version, int code, String url, long size, String sha256, String checksums) {
            this.version = version; versionCode = code; this.url = url; this.size = size;
            this.sha256 = sha256; this.checksums = checksums;
        }
    }
    static final class Downloaded {
        final File file;
        final String sha256;
        Downloaded(File file, String sha256) { this.file = file; this.sha256 = sha256; }
    }
    private final Connections connections;
    private volatile boolean cancelled;
    private volatile HttpURLConnection active;
    ReleaseUpdates() { this(url -> (HttpURLConnection) url.openConnection()); }
    ReleaseUpdates(Connections connections) { this.connections = connections; }

    static int versionCode(String text) throws Failure {
        if (text == null || !text.matches("v?(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)"))
            throw new Failure(R.string.update_invalid);
        try {
            String[] parts = text.replaceFirst("^v", "").split("\\.");
            long major = Long.parseLong(parts[0]), minor = Long.parseLong(parts[1]), patch = Long.parseLong(parts[2]);
            long code = Math.addExact(Math.addExact(Math.multiplyExact(major, 1000000), Math.multiplyExact(minor, 1000)), patch);
            if (minor >= 1000 || patch >= 1000 || code > Integer.MAX_VALUE) throw new Failure(R.string.update_invalid);
            return (int)code;
        } catch (Failure error) { throw error; }
        catch (RuntimeException invalid) { throw new Failure(R.string.update_invalid); }
    }

    static Release parse(JSONObject metadata, String current) throws Failure {
        try {
            if (!Boolean.FALSE.equals(metadata.opt("draft")) || !Boolean.FALSE.equals(metadata.opt("prerelease")))
                throw new Failure(R.string.update_invalid);
            String tag = metadata.getString("tag_name");
            if (!tag.startsWith("v")) throw new Failure(R.string.update_invalid);
            int code = versionCode(tag);
            if (code <= versionCode(current)) return null;
            String url = REPOSITORY + "/releases/download/" + tag + "/" + APK_NAME;
            String checksumUrl = REPOSITORY + "/releases/download/" + tag + "/SHA256SUMS.txt";
            JSONArray assets = metadata.getJSONArray("assets");
            JSONObject apk = null;
            int checksums = 0;
            for (int i = 0; i < assets.length(); i++) {
                JSONObject asset = assets.getJSONObject(i);
                if (APK_NAME.equals(asset.optString("name"))) {
                    if (apk != null) throw new Failure(R.string.update_invalid);
                    apk = asset;
                }
                if ("SHA256SUMS.txt".equals(asset.optString("name")) && checksumUrl.equals(asset.optString("browser_download_url"))) checksums++;
            }
            if (apk == null) throw new Failure(R.string.update_missing);
            Object sizeValue = apk.opt("size");
            long size = apk.optLong("size", -1);
            if (!(sizeValue instanceof Integer || sizeValue instanceof Long) || size < 1 || size > MAX_APK
                    || !url.equals(apk.optString("browser_download_url"))) throw new Failure(R.string.update_invalid);
            String digest = apk.isNull("digest") ? null : apk.getString("digest");
            if (digest != null && !digest.matches("sha256:[0-9a-fA-F]{64}")) throw new Failure(R.string.update_invalid);
            if (digest == null && checksums != 1) throw new Failure(R.string.update_invalid);
            return new Release(tag.substring(1), code, url, size,
                    digest == null ? null : digest.substring(7).toLowerCase(Locale.ROOT), digest == null ? checksumUrl : null);
        } catch (Failure error) { throw error; }
        catch (Exception invalid) { throw new Failure(R.string.update_invalid); }
    }

    void cancel() {
        cancelled = true;
        HttpURLConnection opened = active;
        if (opened != null) opened.disconnect();
    }
    private void checkCancellation() {
        if (cancelled || Thread.currentThread().isInterrupted()) throw new CancellationException();
    }
    private HttpURLConnection open(String address) throws IOException {
        URL url = new URL(address);
        for (int redirect = 0; redirect < 6; redirect++) {
            checkCancellation();
            String host = url.getHost().toLowerCase(Locale.ROOT);
            if (!"https".equals(url.getProtocol()) || url.getUserInfo() != null || url.getRef() != null
                    || (url.getPort() != -1 && url.getPort() != 443)
                    || !(host.equals("api.github.com") || host.equals("github.com")
                    || host.equals("release-assets.githubusercontent.com") || host.equals("objects.githubusercontent.com")))
                throw new Failure(R.string.update_invalid);
            HttpURLConnection connection = connections.open(url);
            active = connection;
            try {
                checkCancellation();
                connection.setConnectTimeout(15000); connection.setReadTimeout(30000);
                connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
                connection.setRequestProperty("User-Agent", "watch2notif-update/" + BuildConfig.VERSION_NAME);
                connection.setRequestProperty("Accept-Encoding", "identity");
                connection.setRequestProperty("Accept", address.equals(LATEST) ? "application/vnd.github+json" : "application/octet-stream");
                int code = connection.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                    String target = connection.getHeaderField("Location");
                    if (target == null) throw new Failure(R.string.update_invalid);
                    url = new URL(url, target); connection.disconnect(); active = null;
                } else {
                    if (code != 200) throw new Failure(code == 403 || code == 429 ? R.string.update_rate_limit : R.string.update_network);
                    return connection;
                }
            } catch (IOException | RuntimeException error) {
                connection.disconnect(); active = null; checkCancellation(); throw error;
            }
        }
        throw new Failure(R.string.update_invalid);
    }
    private byte[] bytes(String url, int limit) throws IOException {
        HttpURLConnection connection = open(url);
        long deadline = System.nanoTime() + 60000000000L;
        try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) != -1) {
                checkCancellation();
                if (System.nanoTime() > deadline || output.size() + count > limit) throw new Failure(R.string.update_invalid);
                output.write(buffer, 0, count);
            }
            checkCancellation(); return output.toByteArray();
        } finally { connection.disconnect(); active = null; }
    }
    Release check(String current) throws IOException {
        byte[] response = bytes(LATEST, 1024 * 1024);
        try { return parse(new JSONObject(new String(response, StandardCharsets.UTF_8)), current); }
        catch (Failure error) { throw error; }
        catch (Exception invalid) { throw new Failure(R.string.update_invalid); }
    }
    Downloaded download(Release release, File directory, Progress progress) throws Exception {
        String expected = release.sha256;
        if (expected == null) {
            String text = new String(bytes(release.checksums, 65536), StandardCharsets.UTF_8);
            for (String line : text.split("\\r?\\n")) {
                if (line.matches("[0-9a-fA-F]{64}  " + java.util.regex.Pattern.quote(APK_NAME))) {
                    if (expected != null) throw new Failure(R.string.update_invalid);
                    expected = line.substring(0, 64).toLowerCase(Locale.ROOT);
                }
            }
            if (expected == null) throw new Failure(R.string.update_invalid);
        }
        if (!directory.isDirectory() && !directory.mkdirs()) throw new Failure(R.string.update_file);
        String operation = UUID.randomUUID().toString();
        File temporary = new File(directory, "download-" + operation + ".part");
        File target = new File(directory, "verified-" + operation + ".apk");
        HttpURLConnection connection = open(release.url);
        long deadline = System.nanoTime() + 300000000000L;
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long done = 0;
            try (InputStream input = connection.getInputStream(); OutputStream output = Files.newOutputStream(temporary.toPath())) {
                byte[] buffer = new byte[65536]; int count;
                while ((count = input.read(buffer)) != -1) {
                    checkCancellation(); done += count;
                    if (System.nanoTime() > deadline || done > release.size) throw new Failure(R.string.update_file);
                    output.write(buffer, 0, count); digest.update(buffer, 0, count); progress.update(done, release.size);
                }
            }
            checkCancellation();
            if (done != release.size || !hex(digest.digest()).equals(expected)) throw new Failure(R.string.update_file);
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING);
            return new Downloaded(target, expected);
        } finally { connection.disconnect(); active = null; Files.deleteIfExists(temporary.toPath()); }
    }
    static String hex(byte[] data) {
        StringBuilder value = new StringBuilder();
        for (byte item : data) value.append(String.format(Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }
    @SuppressWarnings("deprecation")
    private static int signingFlags() { return Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES; }
    @SuppressWarnings("deprecation")
    private static Set<String> signers(PackageInfo info) throws Exception {
        Signature[] values = Build.VERSION.SDK_INT >= 28 && info.signingInfo != null ? info.signingInfo.getApkContentsSigners() : info.signatures;
        Set<String> result = new HashSet<>();
        if (values != null) for (Signature value : values) result.add(hex(MessageDigest.getInstance("SHA-256").digest(value.toByteArray())));
        return result;
    }
    @SuppressWarnings("deprecation")
    static void verifyIdentity(PackageInfo candidate, PackageInfo installed, Release release) throws Exception {
        long code = Build.VERSION.SDK_INT >= 28 ? candidate.getLongVersionCode() : candidate.versionCode;
        long current = Build.VERSION.SDK_INT >= 28 ? installed.getLongVersionCode() : installed.versionCode;
        if (!installed.packageName.equals(candidate.packageName) || !release.version.equals(candidate.versionName)
                || code != release.versionCode || code <= current) throw new Failure(R.string.update_identity);
        Set<String> trusted = signers(installed);
        if (trusted.isEmpty() || !trusted.equals(signers(candidate))) throw new Failure(R.string.update_signature);
    }
    @SuppressWarnings("deprecation")
    static void verify(Context context, Downloaded downloaded, Release release) throws Exception {
        File directory = new File(context.getCacheDir(), "updates").getCanonicalFile();
        File file = downloaded.file.getCanonicalFile();
        if (!directory.equals(file.getParentFile()) || !file.getName().matches("verified-[0-9a-f-]{36}\\.apk") || file.length() != release.size)
            throw new Failure(R.string.update_file);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(file.toPath())) {
            byte[] buffer = new byte[65536]; int count;
            while ((count = input.read(buffer)) != -1) { if (Thread.currentThread().isInterrupted()) throw new CancellationException(); digest.update(buffer, 0, count); }
        }
        if (!downloaded.sha256.equals(hex(digest.digest()))) throw new Failure(R.string.update_file);
        PackageManager manager = context.getPackageManager();
        PackageInfo candidate = manager.getPackageArchiveInfo(file.getAbsolutePath(), signingFlags());
        if (candidate == null) throw new Failure(R.string.update_identity);
        verifyIdentity(candidate, manager.getPackageInfo(context.getPackageName(), signingFlags()), release);
    }
}
