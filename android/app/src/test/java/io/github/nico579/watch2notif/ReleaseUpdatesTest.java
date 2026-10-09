package io.github.nico579.watch2notif;

import android.app.Application;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.Signature;
import android.os.Looper;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 26, application = Application.class)
public class ReleaseUpdatesTest {
    private static final String TAG = "v0.12.0";
    private static final byte[] APK = "test-apk-only".getBytes(StandardCharsets.UTF_8);
    private String digest(byte[] body) throws Exception { return ReleaseUpdates.hex(MessageDigest.getInstance("SHA-256").digest(body)); }
    private JSONObject metadata() throws Exception {
        return new JSONObject().put("draft", false).put("prerelease", false).put("tag_name", TAG)
                .put("assets", new JSONArray().put(new JSONObject().put("name", ReleaseUpdates.APK_NAME)
                        .put("browser_download_url", ReleaseUpdates.REPOSITORY + "/releases/download/" + TAG + "/" + ReleaseUpdates.APK_NAME)
                        .put("size", APK.length).put("digest", "sha256:" + digest(APK))));
    }
    private ReleaseUpdates.Release release() throws Exception { return ReleaseUpdates.parse(metadata(), "0.11.3"); }
    private static final class Connection extends HttpURLConnection {
        final byte[] body;
        int status = 200;
        String location;
        boolean disconnected;
        Connection(URL url, byte[] body) { super(url); this.body = body; }
        @Override public int getResponseCode() { return status; }
        @Override public String getHeaderField(String name) { return "Location".equals(name) ? location : null; }
        @Override public InputStream getInputStream() { return new ByteArrayInputStream(body); }
        @Override public void disconnect() { disconnected = true; }
        @Override public boolean usingProxy() { return false; }
        @Override public void connect() { }
    }
    private interface Action { void run() throws Exception; }
    private void fails(int message, Action action) throws Exception {
        try { action.run(); fail("Should refuse update"); }
        catch (ReleaseUpdates.Failure expected) { assertEquals(message, expected.message); }
    }
    @Test public void versionsAndMetadataSelectOnlyANewerStableOfficialApk() throws Exception {
        assertEquals(12000, release().versionCode); assertEquals("0.12.0", release().version);
        assertNull(ReleaseUpdates.parse(metadata(), "0.12.0"));
        assertNull(ReleaseUpdates.parse(metadata(), "1.0.0"));
        for (String invalid : new String[]{"0.01.3", "0.1000.0", "0.1.1000", "0.1.3-beta", "99999999999999999999.1.0"})
            fails(R.string.update_invalid, () -> ReleaseUpdates.versionCode(invalid));
        fails(R.string.update_invalid, () -> ReleaseUpdates.parse(metadata().put("prerelease", true), "0.11.3"));
        JSONObject duplicate = metadata(); duplicate.getJSONArray("assets").put(duplicate.getJSONArray("assets").getJSONObject(0));
        fails(R.string.update_invalid, () -> ReleaseUpdates.parse(duplicate, "0.11.3"));
        JSONObject external = metadata(); external.getJSONArray("assets").getJSONObject(0).put("browser_download_url", "https://example.org/update.apk");
        fails(R.string.update_invalid, () -> ReleaseUpdates.parse(external, "0.11.3"));
        JSONObject oversized = metadata(); oversized.getJSONArray("assets").getJSONObject(0).put("size", ReleaseUpdates.MAX_APK + 1);
        fails(R.string.update_invalid, () -> ReleaseUpdates.parse(oversized, "0.11.3"));
    }
    @Test public void metadataRequestDoesNotUseProviderCredentialsAndDisablesAutomaticRedirects() throws Exception {
        List<Connection> requests = new ArrayList<>();
        ReleaseUpdates client = new ReleaseUpdates(url -> { Connection c = new Connection(url, metadataBytes()); requests.add(c); return c; });
        assertNotNull(client.check("0.11.3"));
        Connection c = requests.get(0);
        assertEquals(ReleaseUpdates.LATEST, c.getURL().toString());
        assertNull(c.getRequestProperty("Authorization")); assertNull(c.getRequestProperty("x-api-key"));
        assertFalse(c.getInstanceFollowRedirects()); assertEquals(15000, c.getConnectTimeout()); assertTrue(c.disconnected);
    }
    private byte[] metadataBytes() {
        try { return metadata().toString().getBytes(StandardCharsets.UTF_8); } catch (Exception error) { throw new AssertionError(error); }
    }
    @Test public void redirectsCannotDowngradeOrLeaveOfficialHttpsHosts() throws Exception {
        for (String target : new String[]{"http://github.com/file", "https://github.com.evil.example/file", "https://user@github.com/file", "https://github.com:444/file"}) {
            AtomicInteger calls = new AtomicInteger();
            ReleaseUpdates client = new ReleaseUpdates(url -> { calls.incrementAndGet(); Connection c = new Connection(url, new byte[0]); c.status = 302; c.location = target; return c; });
            fails(R.string.update_invalid, () -> client.check("0.11.3")); assertEquals(1, calls.get());
        }
    }
    @Test public void githubAssetRedirectAndMatchingDigestProduceOnlyAFinalApk() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        ReleaseUpdates client = new ReleaseUpdates(url -> {
            Connection c = new Connection(url, APK);
            if (calls.getAndIncrement() == 0) { c.status = 302; c.location = "https://release-assets.githubusercontent.com/test.apk"; }
            return c;
        });
        File directory = Files.createTempDirectory("update-success").toFile();
        ReleaseUpdates.Downloaded downloaded = client.download(release(), directory, (done, total) -> assertTrue(done <= total));
        assertArrayEquals(APK, Files.readAllBytes(downloaded.file.toPath())); assertEquals(digest(APK), downloaded.sha256);
        assertEquals(1, directory.list().length); assertTrue(downloaded.file.getName().endsWith(".apk"));
    }
    @Test public void incompleteCorruptAndOversizedDownloadsDoNotReplaceTheExistingFile() throws Exception {
        for (byte[] bytes : new byte[][]{new byte[1], new byte[APK.length], new byte[APK.length + 1]}) {
            File directory = Files.createTempDirectory("update-refused").toFile(); File existing = new File(directory, ReleaseUpdates.APK_NAME);
            Files.write(existing.toPath(), "old".getBytes(StandardCharsets.UTF_8));
            ReleaseUpdates client = new ReleaseUpdates(url -> new Connection(url, bytes));
            fails(R.string.update_file, () -> client.download(release(), directory, (done, total) -> { }));
            assertEquals("old", new String(Files.readAllBytes(existing.toPath()), StandardCharsets.UTF_8)); assertArrayEquals(new String[]{ReleaseUpdates.APK_NAME}, directory.list());
        }
    }
    @Test public void checksumFallbackRequiresOneExactApkEntry() throws Exception {
        JSONObject metadata = metadata(); metadata.getJSONArray("assets").getJSONObject(0).remove("digest");
        String url = ReleaseUpdates.REPOSITORY + "/releases/download/" + TAG + "/SHA256SUMS.txt";
        metadata.getJSONArray("assets").put(new JSONObject().put("name", "SHA256SUMS.txt").put("browser_download_url", url));
        ReleaseUpdates.Release release = ReleaseUpdates.parse(metadata, "0.11.3");
        for (String text : new String[]{digest(APK) + "  wrong.apk\n", digest(APK) + "  " + ReleaseUpdates.APK_NAME + "\n" + digest(APK) + "  " + ReleaseUpdates.APK_NAME + "\n"}) {
            ReleaseUpdates client = new ReleaseUpdates(address -> new Connection(address, text.getBytes(StandardCharsets.UTF_8)));
            fails(R.string.update_invalid, () -> client.download(release, Files.createTempDirectory("checksum").toFile(), (done, total) -> { }));
        }
        ReleaseUpdates client = new ReleaseUpdates(address -> new Connection(address, address.toString().equals(url)
                ? (digestUnchecked() + "  " + ReleaseUpdates.APK_NAME + "\n").getBytes(StandardCharsets.UTF_8) : APK));
        assertEquals(digest(APK), client.download(release, Files.createTempDirectory("checksum-ok").toFile(), (done, total) -> { }).sha256);
    }
    private String digestUnchecked() { try { return digest(APK); } catch (Exception error) { throw new AssertionError(error); } }
    @Test public void apiLimitsAndCancellationProduceSafeErrorsWithoutStartingADownload() throws Exception {
        ReleaseUpdates client = new ReleaseUpdates(url -> { Connection c = new Connection(url, new byte[0]); c.status = 429; return c; });
        fails(R.string.update_rate_limit, () -> client.check("0.11.3"));
        ReleaseUpdates cancelled = new ReleaseUpdates(url -> { fail("Cancelled requests stay offline"); return null; }); cancelled.cancel();
        try { cancelled.check("0.11.3"); fail(); } catch (java.util.concurrent.CancellationException expected) { }
    }
    private PackageInfo identity(String name, int code, String version, String signer) {
        PackageInfo value = new PackageInfo(); value.packageName = name; value.versionCode = code; value.versionName = version;
        value.signatures = new Signature[]{new Signature(signer.getBytes(StandardCharsets.UTF_8))}; return value;
    }
    @Test public void apkIdentityRequiresMatchingPackageVersionAndInstalledSigner() throws Exception {
        PackageInfo installed = identity("io.github.nico579.watch2notif", 11003, "0.11.3", "trusted");
        PackageInfo candidate = identity(installed.packageName, 12000, "0.12.0", "trusted");
        ReleaseUpdates.verifyIdentity(candidate, installed, release());
        candidate.signatures = identity("x", 1, "x", "other").signatures;
        fails(R.string.update_signature, () -> ReleaseUpdates.verifyIdentity(candidate, installed, release()));
        candidate.signatures = installed.signatures; candidate.packageName = "another.app";
        fails(R.string.update_identity, () -> ReleaseUpdates.verifyIdentity(candidate, installed, release()));
        candidate.packageName = installed.packageName; candidate.versionCode = 11003;
        fails(R.string.update_identity, () -> ReleaseUpdates.verifyIdentity(candidate, installed, release()));
    }
    @Test public void cachedApkIsRehashedBeforeTheInstallerAndMustStayInsideItsProviderDirectory() throws Exception {
        Context context = RuntimeEnvironment.getApplication(); File directory = new File(context.getCacheDir(), "updates"); assertTrue(directory.isDirectory() || directory.mkdirs());
        File apk = new File(directory, "verified-00000000-0000-0000-0000-000000000001.apk"); Files.write(apk.toPath(), new byte[APK.length]);
        fails(R.string.update_file, () -> ReleaseUpdates.verify(context, new ReleaseUpdates.Downloaded(apk, digest(APK)), release()));
        File outside = new File(context.getFilesDir(), ReleaseUpdates.APK_NAME); Files.write(outside.toPath(), APK);
        fails(R.string.update_file, () -> ReleaseUpdates.verify(context, new ReleaseUpdates.Downloaded(outside, digest(APK)), release()));
    }
    @Test public void retainedSessionFinishesWhileDetachedAndReverifiesBeforeInstalling() throws Exception {
        Context context = RuntimeEnvironment.getApplication(); AtomicInteger verifications = new AtomicInteger(), installations = new AtomicInteger();
        UpdateSession session = new UpdateSession(context, () -> new ReleaseUpdates(url -> new Connection(url, APK)), (file, version) -> verifications.incrementAndGet());
        session.release = release(); session.state = UpdateSession.State.AVAILABLE; session.download();
        Thread worker = ReflectionHelpers.getField(session, "worker"); worker.join(3000); assertFalse(worker.isAlive()); shadowOf(Looper.getMainLooper()).idle();
        assertEquals(UpdateSession.State.READY, session.state); assertEquals(1, verifications.get());
        session.prepareInstall(file -> installations.incrementAndGet());
        worker = ReflectionHelpers.getField(session, "worker"); worker.join(3000); shadowOf(Looper.getMainLooper()).idle();
        assertEquals(2, verifications.get()); assertEquals(1, installations.get()); session.close();
    }
    @Test public void cancellationDiscardsALateMetadataResult() throws Exception {
        CountDownLatch opened = new CountDownLatch(1), release = new CountDownLatch(1);
        UpdateSession session = new UpdateSession(RuntimeEnvironment.getApplication(), () -> new ReleaseUpdates(url -> {
            opened.countDown(); try { release.await(3, TimeUnit.SECONDS); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            return new Connection(url, metadataBytes());
        }), (apk, version) -> { });
        session.check(true); assertTrue(opened.await(3, TimeUnit.SECONDS)); session.cancel(); release.countDown();
        Thread worker = ReflectionHelpers.getField(session, "worker"); worker.join(3000); shadowOf(Looper.getMainLooper()).idle();
        assertEquals(UpdateSession.State.IDLE, session.state); assertNull(session.release); session.close();
    }
}
