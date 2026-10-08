package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class Models {
    static final String[] KINDS = ProviderRegistry.BUILTINS.kinds();
    static final int[] LABELS = ProviderRegistry.BUILTINS.labels();
    static final int[] HINTS = ProviderRegistry.BUILTINS.hints();
    static final int MAX_SOURCES = 50;

    static int kindIndex(String kind) {
        return ProviderRegistry.BUILTINS.indexOf(kind);
    }

    static int defaultInterval(String kind) {
        return ProviderRegistry.BUILTINS.require(kind).metadata().defaultInterval;
    }

    static boolean webLink(String value) {
        try {
            URI uri = new URI(value);
            return ("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme()))
                    && uri.getHost() != null && uri.getRawUserInfo() == null;
        } catch (Exception ignored) { return false; }
    }

    static String videoId(String source) {
        if (source.matches("[A-Za-z0-9_-]{11}")) return source;
        if (!webLink(source)) throw new IllegalArgumentException("video");
        URI uri = URI.create(source);
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        if (!(host.equals("youtu.be") || host.equals("youtube.com") || host.endsWith(".youtube.com")
                || host.equals("youtube-nocookie.com") || host.endsWith(".youtube-nocookie.com"))) {
            throw new IllegalArgumentException("video");
        }
        Pattern pattern = Pattern.compile("(?:[?&]v=|youtu\\.be/|/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})(?:[?&#/]|$)");
        Matcher matcher = pattern.matcher(source);
        if (!matcher.find()) throw new IllegalArgumentException("video");
        return matcher.group(1);
    }

    static String hash(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder();
            for (byte b : digest) result.append(String.format(Locale.ROOT, "%02x", b & 255));
            return result.toString();
        } catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }

    static String str(JSONObject json, String key, String fallback) {
        return json == null || json.isNull(key) ? fallback : json.optString(key, fallback);
    }

    static long timestamp(String raw) {
        if (raw == null || raw.trim().isEmpty()) return 0;
        try { return Instant.parse(raw).toEpochMilli(); } catch (Exception ignored) { }
        try { return OffsetDateTime.parse(raw).toInstant().toEpochMilli(); } catch (Exception ignored) { }
        try { return ZonedDateTime.parse(raw, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli(); }
        catch (Exception ignored) { }
        for (String format : new String[]{"EEE, d MMM yyyy HH:mm:ss Z", "d MMM yyyy HH:mm:ss Z"}) {
            try { return ZonedDateTime.parse(raw, DateTimeFormatter.ofPattern(format, Locale.US)).toInstant().toEpochMilli(); }
            catch (Exception ignored) { }
        }
        return 0;
    }

    static String compact(String text, int limit) {
        String cleaned = text == null ? "" : text.replaceAll("\\s+", " ").trim();
        return cleaned.length() <= limit ? cleaned : cleaned.substring(0, limit);
    }

    static final class Feed {
        final String key, label, kind, url, filter;
        final int interval;
        final boolean enabled;

        Feed(String key, String label, String kind, String url, int interval, boolean enabled) {
            this(key, label, kind, url, interval, enabled, "");
        }

        Feed(String key, String label, String kind, String url, int interval, boolean enabled, String filter) {
            this.key = key; this.label = label.trim(); this.kind = kind; this.url = url.trim();
            this.filter = filter.trim();
            this.interval = interval; this.enabled = enabled;
            if (key.trim().isEmpty() || key.length() > 150 || this.label.trim().isEmpty() || this.label.length() > 200
                    || this.url.length() > 8192 || this.filter.length() > 4000
                    || interval < 5 || interval > 604800 || kindIndex(kind) < 0) {
                throw new IllegalArgumentException("source");
            }
            ProviderRegistry.BUILTINS.require(kind).validateSource(this.url);
        }

        String fingerprint() { return hash(kind + "\n" + url); }

        Feed withEnabled(boolean value) { return new Feed(key, label, kind, url, interval, value, filter); }

        JSONObject json() throws JSONException {
            return new JSONObject().put("key", key).put("label", label).put("kind", kind).put("url", url)
                    .put("interval_seconds", interval).put("enabled", enabled).put("filtre_ia", filter);
        }

        static Feed fromJson(JSONObject json, int globalInterval, boolean newKey) {
            String kind = str(json, "kind", "rss");
            if (json.has("enabled") && !(json.opt("enabled") instanceof Boolean)) throw new IllegalArgumentException("enabled");
            if (!json.isNull("interval_seconds")) {
                Object raw = json.opt("interval_seconds");
                if (!(raw instanceof Number) || ((Number) raw).doubleValue() != ((Number)raw).intValue()) throw new IllegalArgumentException("interval");
            }
            int interval = json.isNull("interval_seconds") ? defaultInterval(kind) : json.optInt("interval_seconds", globalInterval);
            String label = str(json, "label", "").trim();
            String address = str(json, "url", "").trim();
            return new Feed(newKey ? UUID.randomUUID().toString() : json.optString("key", UUID.randomUUID().toString()),
                    label.isEmpty() ? address : label, kind, address, interval, json.optBoolean("enabled", true), str(json, "filtre_ia", ""));
        }

        static List<Feed> importConfig(JSONObject config) throws JSONException {
            JSONArray rows = config.getJSONArray("feeds");
            if (rows.length() > 200) throw new IllegalArgumentException("source limit");
            List<Feed> result = new ArrayList<>();
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                if (str(row, "url", "").trim().isEmpty()) continue;
                result.add(fromJson(row, config.optInt("poll_interval_seconds", 60), true));
            }
            if (result.size() > MAX_SOURCES) throw new IllegalArgumentException("source limit");
            return result;
        }
    }

    static final class Entry {
        final String id, title, author, link, summary;
        final long created;

        Entry(String id, String title, String author, String link, String summary, long created) {
            this.title = compact(title, 300); this.author = compact(author, 150);
            this.link = link == null ? "" : link;
            this.summary = compact(summary, 4000); this.created = created;
            this.id = id == null || id.trim().isEmpty() ? (this.link.trim().isEmpty() ? hash(this.title + "|" + this.summary) : this.link) : id;
        }

        JSONObject json() throws JSONException {
            return new JSONObject().put("id", id).put("title", title).put("author", author).put("link", link)
                    .put("summary", summary).put("created", created);
        }

        static Entry fromJson(JSONObject j) {
            return new Entry(str(j, "id", ""), str(j, "title", ""), str(j, "author", ""),
                    str(j, "link", ""), str(j, "summary", ""), j.optLong("created"));
        }
    }

    static final class PollState {
        static final int MAX_SEEN = 4000;
        boolean initialized;
        long watermark, lastAttempt, lastSuccess;
        String fingerprint = "", error = "";
        int httpCode;
        final LinkedHashSet<String> seen = new LinkedHashSet<>();
        final LinkedHashMap<String, Entry> pending = new LinkedHashMap<>();
        JSONObject decisions = new JSONObject();

        void merge(List<Entry> entries, long now) {
            long newest = watermark;
            for (Entry entry : entries) {
                long date = entry.created > 0 && entry.created <= now + 86400000L ? entry.created : 0;
                newest = Math.max(newest, date);
                if (seen.contains(entry.id) || pending.containsKey(entry.id)) continue;
                if (!initialized || (date > 0 && watermark > 0 && date < watermark - 300000L)) seen.add(entry.id);
                else pending.put(entry.id, entry);
            }
            initialized = true;
            watermark = newest;
            trim();
        }

        void delivered(String id) { pending.remove(id); decisions.remove(id); seen.add(id); trim(); }

        private void trim() {
            while (seen.size() > MAX_SEEN) seen.remove(seen.iterator().next());
        }

        JSONObject json() throws JSONException {
            JSONArray waiting = new JSONArray();
            for (Entry entry : pending.values()) waiting.put(entry.json());
            return new JSONObject().put("initialized", initialized).put("fingerprint", fingerprint)
                    .put("seen", new JSONArray(seen)).put("pending", waiting).put("decisions", decisions).put("watermark", watermark)
                    .put("last_attempt", lastAttempt).put("last_success", lastSuccess)
                    .put("error", error).put("http_code", httpCode);
        }

        static PollState fromJson(JSONObject json) throws JSONException {
            PollState result = new PollState();
            if (json == null) return result;
            result.initialized = json.optBoolean("initialized"); result.fingerprint = str(json, "fingerprint", "");
            result.watermark = json.optLong("watermark"); result.lastAttempt = json.optLong("last_attempt");
            result.lastSuccess = json.optLong("last_success"); result.error = str(json, "error", "");
            result.httpCode = json.optInt("http_code");
            if (json.optJSONObject("decisions") != null) result.decisions = new JSONObject(json.getJSONObject("decisions").toString());
            JSONArray ids = json.optJSONArray("seen"), waiting = json.optJSONArray("pending");
            if (ids != null) for (int i = 0; i < ids.length(); i++) result.seen.add(ids.getString(i));
            if (waiting != null) for (int i = 0; i < waiting.length(); i++) {
                Entry entry = Entry.fromJson(waiting.getJSONObject(i));
                if (!result.seen.contains(entry.id)) result.pending.put(entry.id, entry);
            }
            return result;
        }
    }
}
