package io.github.nico579.watch2notif;

import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

/** One atomic document and one lock for source edits, state and history. Network I/O never holds this lock. */
final class Store {
    private static Store instance;
    private final AtomicFile file;
    private JSONObject data;

    static synchronized Store get(Context context) {
        if (instance == null) instance = new Store(context.getApplicationContext());
        return instance;
    }

    Store(Context context) {
        file = new AtomicFile(new File(context.getFilesDir(), "watch2notif.json"));
        try {
            data = file.getBaseFile().exists() ? new JSONObject(new String(file.readFully(), StandardCharsets.UTF_8))
                    : new JSONObject().put("feeds", new JSONArray()).put("states", new JSONObject())
                    .put("history", new JSONArray()).put("paused", false);
            // Validate existing data before any code can write a replacement.
            feeds(); data.getJSONObject("states"); data.getJSONArray("history");
        } catch (Exception failure) { throw new IllegalStateException("Cannot read monitoring data", failure); }
    }

    private JSONObject copy() throws JSONException { return new JSONObject(data.toString()); }

    private void save(JSONObject replacement) throws IOException {
        FileOutputStream output = null;
        try {
            output = file.startWrite();
            output.write(replacement.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(output);
            data = replacement;
        } catch (IOException failure) {
            if (output != null) file.failWrite(output);
            throw failure;
        }
    }

    synchronized List<Feed> feeds() {
        try {
            List<Feed> result = new ArrayList<>();
            JSONArray rows = data.getJSONArray("feeds");
            for (int i = 0; i < rows.length(); i++) result.add(Feed.fromJson(rows.getJSONObject(i), 60, false));
            return result;
        } catch (JSONException failure) { throw new IllegalStateException(failure); }
    }

    synchronized Feed find(String key) {
        for (Feed feed : feeds()) if (feed.key.equals(key)) return feed;
        return null;
    }

    synchronized boolean current(Feed feed, boolean manual) {
        Feed current = find(feed.key);
        return current != null && current.enabled && current.fingerprint().equals(feed.fingerprint())
                && (manual || !paused());
    }

    synchronized void putFeed(Feed feed) throws IOException {
        List<Feed> rows = feeds();
        Feed previous = find(feed.key);
        rows.removeIf(row -> row.key.equals(feed.key));
        if (rows.size() >= MAX_SOURCES) throw new IllegalArgumentException("source limit");
        rows.add(feed);
        try {
            JSONObject updated = copy();
            JSONArray serialized = new JSONArray();
            for (Feed row : rows) serialized.put(row.json());
            updated.put("feeds", serialized);
            if (previous != null && !previous.fingerprint().equals(feed.fingerprint())) updated.getJSONObject("states").remove(feed.key);
            save(updated);
        } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized void deleteFeed(String key) throws IOException {
        try {
            JSONObject updated = copy();
            JSONArray serialized = new JSONArray();
            for (Feed row : feeds()) if (!row.key.equals(key)) serialized.put(row.json());
            updated.put("feeds", serialized); updated.getJSONObject("states").remove(key);
            save(updated);
        } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized void replaceFeeds(List<Feed> feeds) throws IOException {
        replaceFeeds(feeds, null);
    }

    synchronized void replaceFeeds(List<Feed> feeds, JSONObject encryptedCredentials) throws IOException {
        try {
            if (feeds.size() > MAX_SOURCES) throw new IllegalArgumentException("source limit");
            JSONArray serialized = new JSONArray();
            for (Feed feed : feeds) serialized.put(feed.json());
            JSONObject updated = copy().put("feeds", serialized).put("states", new JSONObject());
            if (encryptedCredentials != null) updated.put("credentials", encryptedCredentials);
            save(updated);
        } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized boolean paused() { return data.optBoolean("paused", false); }

    synchronized JSONObject credentials() {
        try {
            JSONObject values = data.optJSONObject("credentials");
            return values == null ? new JSONObject() : new JSONObject(values.toString());
        } catch (JSONException failure) { throw new IllegalStateException(failure); }
    }

    synchronized void credentials(JSONObject values) throws IOException {
        try { save(copy().put("credentials", values)); } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized void paused(boolean value) throws IOException {
        try { save(copy().put("paused", value)); } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized PollState state(Feed feed) {
        try {
            PollState state = PollState.fromJson(data.getJSONObject("states").optJSONObject(feed.key));
            if (!state.fingerprint.equals(feed.fingerprint())) {
                state = new PollState(); state.fingerprint = feed.fingerprint();
            }
            return state;
        } catch (JSONException failure) { throw new IllegalStateException(failure); }
    }

    synchronized void state(Feed feed, PollState state) throws IOException {
        try {
            JSONObject updated = copy(); updated.getJSONObject("states").put(feed.key, state.json()); save(updated);
        } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized void delivered(Feed feed, PollState state, Entry entry) throws IOException {
        try {
            JSONObject updated = copy();
            state.delivered(entry.id);
            updated.getJSONObject("states").put(feed.key, state.json());
            JSONArray rows = new JSONArray();
            String id = hash(feed.key + "\n" + entry.id);
            rows.put(new JSONObject().put("id", id).put("feed_label", feed.label).put("title", entry.title)
                    .put("author", entry.author).put("summary", entry.summary).put("link", entry.link)
                    .put("timestamp", System.currentTimeMillis() / 1000.0));
            JSONArray existing = data.getJSONArray("history");
            for (int i = 0; i < existing.length() && rows.length() < 200; i++) {
                JSONObject old = existing.getJSONObject(i);
                if (!id.equals(old.optString("id"))) rows.put(old);
            }
            updated.put("history", rows); save(updated);
        } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized JSONArray history() {
        try { return new JSONArray(data.getJSONArray("history").toString()); }
        catch (JSONException failure) { throw new IllegalStateException(failure); }
    }

    synchronized void clearHistory() throws IOException {
        try { save(copy().put("history", new JSONArray())); } catch (JSONException failure) { throw new IOException(failure); }
    }

    synchronized JSONObject exportConfig() throws JSONException {
        JSONArray rows = new JSONArray();
        for (Feed feed : feeds()) rows.put(feed.json());
        return new JSONObject().put("poll_interval_seconds", 60).put("feeds", rows)
                .put("lang", language()).put("android_paused", paused());
    }

    synchronized String language() { return data.optString("lang", ""); }

    synchronized void language(String value) throws IOException {
        try { save(copy().put("lang", value)); } catch (JSONException failure) { throw new IOException(failure); }
    }
}
