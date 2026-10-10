package io.github.nico579.watch2notif;

import android.app.Application;
import android.content.Context;
import android.content.ContextWrapper;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import static io.github.nico579.watch2notif.Models.*;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class CoreTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    private Context context;
    private Store store;
    private Feed feed;

    @Before public void setUp() throws Exception {
        File directory = temporary.newFolder();
        context = new ContextWrapper(RuntimeEnvironment.getApplication()) { @Override public File getFilesDir() { return directory; } };
        store = new Store(context); feed = new Feed("rss", "Feed", "rss", "https://example.org/rss", 60, true);
        store.putFeed(feed);
    }

    private Entry entry(String id, long timestamp) { return new Entry(id, id, "author", "https://example.org/" + id, "body", timestamp); }

    @Test public void baselineIsQuietIncludingInitiallyEmptyFeed() {
        PollState state = new PollState(); state.merge(List.of(), 1000000);
        assertTrue(state.initialized); assertTrue(state.pending.isEmpty());
        state.merge(List.of(entry("new", 999000)), 1000000);
        assertTrue(state.pending.containsKey("new"));
    }

    @Test public void lateBackfillIsAbsorbedButRecentAndUndatedItemsRemainPending() {
        PollState state = new PollState(); state.merge(List.of(entry("base", 1000000)), 1000000);
        state.merge(List.of(entry("old", 1000), entry("grace", 800000), entry("undated", 0), entry("future", 100000000)), 1000000);
        assertTrue(state.seen.contains("old")); assertEquals(3, state.pending.size()); assertEquals(1000000, state.watermark);
    }

    @Test public void pendingItemsSurviveRestartAndNotificationFailure() throws Exception {
        PollState state = store.state(feed); state.merge(List.of(entry("base", 0)), 1000);
        state.merge(List.of(entry("new", 0)), 2000); store.state(feed, state);
        Store reopened = new Store(context); assertTrue(reopened.state(feed).pending.containsKey("new"));
        reopened.delivered(feed, reopened.state(feed), entry("new", 0));
        assertTrue(new Store(context).state(feed).pending.isEmpty()); assertEquals(1, reopened.history().length());
    }

    @Test public void removingOneHistoryLineKeepsTheOthersAndSurvivesARestart() throws Exception {
        for (String id : new String[]{"a", "b", "c"}) store.delivered(feed, store.state(feed), entry(id, 0));
        // Newest first: c, b, a. The screen drew this list; then a fourth line lands on top before the tap.
        org.json.JSONObject middle = store.history().getJSONObject(1);
        assertEquals("b", middle.getString("title"));
        store.delivered(feed, store.state(feed), entry("d", 0));
        assertTrue(store.removeHistory(middle));
        assertFalse(store.removeHistory(middle)); // already gone: nothing else is removed
        org.json.JSONArray rows = new Store(context).history();
        assertEquals(3, rows.length());
        assertEquals("d", rows.getJSONObject(0).getString("title")); assertEquals("c", rows.getJSONObject(1).getString("title"));
        assertEquals("a", rows.getJSONObject(2).getString("title"));
    }

    @Test public void historyLinesWithoutAnIdAreRemovedByTimestampAndLink() throws Exception {
        store.delivered(feed, store.state(feed), entry("x", 0));
        org.json.JSONObject row = store.history().getJSONObject(0);
        row.remove("id"); // as written by an older version
        assertFalse("a line that does have an id must not match by timestamp", store.removeHistory(row));
        assertEquals(1, store.history().length());
        org.json.JSONObject legacy = new org.json.JSONObject().put("timestamp", 5.5).put("link", "https://old.example/1").put("title", "old");
        assertFalse(store.removeHistory(legacy)); // absent
    }

    @Test public void ruleChangeKeepsSeenIdsButAddressChangeReseeds() throws Exception {
        PollState state = store.state(feed); state.merge(List.of(entry("base", 0)), 1000); store.state(feed, state);
        Feed filtered = new Feed(feed.key, feed.label, feed.kind, feed.url, 60, true, "Questions only"); store.putFeed(filtered);
        assertTrue(store.state(filtered).seen.contains("base"));
        Feed changed = new Feed(feed.key, feed.label, feed.kind, "https://example.org/other", 60, true); store.putFeed(changed);
        assertFalse(store.state(changed).initialized);
    }

    @Test public void portableExportNeverIncludesCredentialsOrHistory() throws Exception {
        store.credentials(new JSONObject().put("claude", "encrypted-private-value"));
        String exported = store.exportConfig().toString();
        assertFalse(exported.contains("encrypted-private-value")); assertFalse(exported.contains("history"));
    }

    @Test public void invalidImportIsAtomicAndStrict() throws Exception {
        JSONObject invalid = new JSONObject("{\"feeds\":[{\"label\":\"bad\",\"kind\":\"rss\",\"url\":\"file:///tmp/x\"}]}");
        try { Feed.importConfig(invalid); fail(); } catch (IllegalArgumentException expected) { }
        assertEquals(1, store.feeds().size());
    }

    @Test public void corruptedStateIsPreserved() throws Exception {
        File file = new File(context.getFilesDir(), "watch2notif.json"); Files.write(file.toPath(), "broken-json".getBytes(StandardCharsets.UTF_8));
        try { new Store(context); fail(); } catch (IllegalStateException expected) { }
        assertEquals("broken-json", new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }

    @Test public void sourceEditDuringNetworkRequestCannotCommitOldResponse() throws Exception {
        Network.Transport transport = (url, token, body, api) -> {
            try { store.putFeed(new Feed("rss", "Changed", "rss", "https://example.org/new", 60, true)); }
            catch (Exception failure) { throw new SourceException("storage"); }
            return "<rss><channel><item><guid>old</guid></item></channel></rss>".getBytes(StandardCharsets.UTF_8);
        };
        PollEngine engine = new PollEngine(context, store, transport, (c, f, e) -> { fail(); return false; }, name -> "", () -> true);
        engine.poll(true);
        assertFalse(store.state(store.find("rss")).initialized);
    }

    @Test public void filteredItemsAreSeenAndAcceptedReasonIsPrepended() throws Exception {
        Feed filtered = new Feed(feed.key, feed.label, feed.kind, feed.url, 60, true, "Questions only"); store.putFeed(filtered);
        PollState seeded = store.state(filtered); seeded.merge(List.of(), 1000); store.state(filtered, seeded);
        AtomicInteger judgments = new AtomicInteger(); List<Entry> alerts = new ArrayList<>();
        Network.Transport transport = (url, token, body, api) -> {
            if (url.contains("anthropic")) {
                boolean relevant = judgments.getAndIncrement() == 0;
                return ("{\"content\":[{\"type\":\"text\",\"text\":\"{\\\"pertinent\\\":" + relevant + ",\\\"raison\\\":\\\"a question\\\"}\"}]}").getBytes(StandardCharsets.UTF_8);
            }
            return "<rss><channel><item><guid>reject</guid></item><item><guid>accept</guid><description>body</description></item></channel></rss>".getBytes(StandardCharsets.UTF_8);
        };
        PollEngine engine = new PollEngine(context, store, transport, (c, f, e) -> { alerts.add(e); return true; }, name -> "test-key", () -> true);
        PollEngine.Report report = engine.poll(true);
        assertEquals(1, report.filtered); assertEquals(1, report.sent); assertEquals(2, judgments.get());
        assertTrue(alerts.get(0).summary.startsWith("a question |"));
        engine.poll(true); assertEquals(2, judgments.get()); assertTrue(store.state(filtered).pending.isEmpty());
    }

    @Test public void blockedNotificationsDoNotSpendClaudeCallsAndPendingSurvives() throws Exception {
        Feed filtered = new Feed(feed.key, feed.label, feed.kind, feed.url, 60, true, "questions"); store.putFeed(filtered);
        PollState seeded = store.state(filtered); seeded.merge(List.of(), 1000); store.state(filtered, seeded);
        Network.Transport transport = (url, token, body, api) -> {
            assertFalse(url.contains("anthropic"));
            return "<rss><channel><item><guid>new</guid></item></channel></rss>".getBytes(StandardCharsets.UTF_8);
        };
        new PollEngine(context, store, transport, (c, f, e) -> false, name -> "key", () -> false).poll(true);
        assertTrue(store.state(filtered).pending.containsKey("new"));
    }

    @Test public void missingClaudeKeyFailsOpenWithAnExplicitWarning() throws Exception {
        Feed filtered = new Feed(feed.key, feed.label, feed.kind, feed.url, 60, true, "questions"); store.putFeed(filtered);
        PollState seeded = store.state(filtered); seeded.merge(List.of(), 1000); store.state(filtered, seeded);
        List<Entry> alerts = new ArrayList<>();
        Network.Transport transport = (url, token, body, api) -> "<rss><channel><item><guid>new</guid></item></channel></rss>".getBytes(StandardCharsets.UTF_8);
        new PollEngine(context, store, transport, (c, f, e) -> { alerts.add(e); return true; }, name -> "", () -> true).poll(true);
        assertEquals(1, alerts.size()); assertTrue(alerts.get(0).summary.contains("notified without filtering"));
    }

    @Test public void successfulClaudeDecisionIsCachedUntilNotificationSucceeds() throws Exception {
        Feed filtered = new Feed(feed.key, feed.label, feed.kind, feed.url, 60, true, "questions"); store.putFeed(filtered);
        PollState seeded = store.state(filtered); seeded.merge(List.of(), 1000); store.state(filtered, seeded);
        AtomicInteger calls = new AtomicInteger(); AtomicBoolean deliver = new AtomicBoolean(false);
        Network.Transport transport = (url, token, body, api) -> {
            if (url.contains("anthropic")) { calls.incrementAndGet(); return "{\"content\":[{\"type\":\"text\",\"text\":\"{\\\"pertinent\\\":true,\\\"raison\\\":\\\"ok\\\"}\"}]}".getBytes(StandardCharsets.UTF_8); }
            return "<rss><channel><item><guid>new</guid></item></channel></rss>".getBytes(StandardCharsets.UTF_8);
        };
        PollEngine engine = new PollEngine(context, store, transport, (c, f, e) -> deliver.get(), name -> "key", () -> true);
        engine.poll(true); deliver.set(true); engine.poll(true);
        assertEquals(1, calls.get()); assertTrue(store.state(filtered).pending.isEmpty());
    }
}
