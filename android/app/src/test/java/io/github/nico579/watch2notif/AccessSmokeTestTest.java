package io.github.nico579.watch2notif;

import android.app.Application;
import android.app.AlertDialog;
import android.os.Looper;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.android.controller.ActivityController;
import org.robolectric.annotation.Config;
import org.robolectric.shadows.ShadowAlertDialog;
import org.robolectric.util.ReflectionHelpers;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static io.github.nico579.watch2notif.Models.*;
import static org.junit.Assert.*;
import static org.robolectric.Shadows.shadowOf;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class AccessSmokeTestTest {
    @Before public void reset() throws Exception {
        ReflectionHelpers.setStaticField(Store.class, "instance", null);
        File saved = new File(RuntimeEnvironment.getApplication().getFilesDir(), "watch2notif.json");
        if (saved.exists()) assertTrue(saved.delete()); Notifications.channels(RuntimeEnvironment.getApplication());
    }
    private Feed rss() { return new Feed("r", "RSS", "rss", "https://example.org/feed.xml", 60, true); }
    private byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private AccessSmokeTest test(Network.Transport transport, Provider.Credentials credentials) {
        return new AccessSmokeTest(RuntimeEnvironment.getApplication(), transport, credentials);
    }
    @Test public void allFiveRegisteredProvidersAndClaudeAreCheckedWithoutChangingMonitoringState() throws Exception {
        List<Feed> feeds = Arrays.asList(rss(), new Feed("g", "Issues", "github_issues", "nico579/watch2notif", 300, true),
                new Feed("d", "Discussion", "github_discussion", "nico579/watch2notif#1", 300, true),
                new Feed("s", "Sponsors", "github_sponsors", "nico579", 1800, true),
                new Feed("y", "YouTube", "youtube_comments", "dQw4w9WgXcQ", 300, true));
        Store store = Store.get(RuntimeEnvironment.getApplication()); store.replaceFeeds(feeds);
        String before = store.exportConfig().toString();
        List<String> requests = new CopyOnWriteArrayList<>();
        Network.Transport transport = (url, token, body, api) -> {
            requests.add(url.split("\\?")[0]);
            if (url.contains("anthropic.com")) {
                assertEquals("claude-test", token); assertTrue(body.contains("Test message only."));
                return bytes("{\"content\":[{\"type\":\"text\",\"text\":\"{\\\"pertinent\\\":true,\\\"raison\\\":\\\"OK\\\"}\"}]}");
            }
            if (url.contains("/graphql")) {
                assertEquals("github-test", token);
                return bytes(body.contains("sponsorshipsAsMaintainer") ? "{\"data\":{\"user\":{\"sponsorshipsAsMaintainer\":{\"nodes\":[]}}}}"
                        : "{\"data\":{\"repository\":{\"discussion\":{\"title\":\"D\",\"comments\":{\"nodes\":[]}}}}}");
            }
            if (url.contains("youtube")) { assertTrue(url.contains("youtube-test")); return bytes("{\"items\":[]}"); }
            if (url.contains("api.github.com")) { assertEquals("github-test", token); return bytes("[]"); }
            assertTrue(token.isEmpty()); return bytes("<rss><channel/></rss>");
        };
        List<AccessSmokeTest.Row> rows = test(transport, name -> name + "-test").run(feeds, row -> { });
        assertEquals(6, rows.size()); assertEquals(6, requests.size());
        for (AccessSmokeTest.Row row : rows) assertEquals(row.label, AccessSmokeTest.Outcome.OK, row.outcome);
        assertEquals(before, store.exportConfig().toString());
        for (Feed feed : feeds) { assertEquals(0, store.state(feed).lastAttempt); assertFalse(store.state(feed).initialized); assertTrue(store.state(feed).pending.isEmpty()); }
        assertEquals(0, store.history().length());
    }
    @Test public void missingKeysAndDisabledSourcesAreReportedWithoutRequests() throws Exception {
        Feed discussion = new Feed("d", "Discussion", "github_discussion", "nico579/watch2notif#1", 300, true);
        List<Feed> feeds = Arrays.asList(discussion, new Feed("y", "YouTube", "youtube_comments", "dQw4w9WgXcQ", 300, true), rss().withEnabled(false));
        List<AccessSmokeTest.Row> rows = test((url, token, body, api) -> { fail("Missing credentials must stay offline"); return null; }, name -> "").run(feeds, row -> { });
        assertEquals("github_token", rows.get(0).error); assertEquals("youtube_key", rows.get(1).error);
        assertEquals(AccessSmokeTest.Outcome.SKIPPED, rows.get(2).outcome); assertEquals(AccessSmokeTest.Outcome.SKIPPED, rows.get(3).outcome);
    }
    @Test public void anAiRuleWithNoClaudeKeyIsAFailureEvenWhenTheSourceIsAccessible() throws Exception {
        Feed feed = new Feed("r", "RSS", "rss", "https://example.org/feed.xml", 60, true, "Only relevant messages");
        List<AccessSmokeTest.Row> rows = test((url, token, body, api) -> bytes("<rss><channel/></rss>"), name -> "").run(Collections.singletonList(feed), row -> { });
        assertEquals(AccessSmokeTest.Outcome.OK, rows.get(0).outcome); assertEquals("claude_key", rows.get(1).error);
    }
    @Test public void failedAuthenticationPermissionsAndClaudeParsingRemainVisible() throws Exception {
        for (int status : new int[]{401, 403, 429}) {
            List<AccessSmokeTest.Row> rows = test((url, token, body, api) -> { throw new SourceException("http", status); }, name -> "test").run(Collections.singletonList(rss()), row -> { });
            assertEquals(status, rows.get(0).httpCode); assertEquals(AccessSmokeTest.Outcome.FAILED, rows.get(0).outcome);
            assertEquals(status == 401 ? R.string.error_unauthorized : status == 403 ? R.string.error_forbidden : R.string.error_rate_limit,
                    SourceException.message(rows.get(0).error, status));
        }
        List<AccessSmokeTest.Row> malformed = test((url, token, body, api) -> bytes(url.contains("anthropic.com") ? "{}" : "<rss><channel/></rss>"), name -> "test")
                .run(Collections.singletonList(rss()), row -> { });
        assertEquals("parse", malformed.get(1).error);
    }
    @Test public void slowSourcesBecomeExplicitTimeoutsAndOtherResultsAreNotLost() throws Exception {
        AccessSmokeTest smoke = new AccessSmokeTest(RuntimeEnvironment.getApplication(), (url, token, body, api) -> {
            try { Thread.sleep(5000); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            throw new SourceException("network");
        }, name -> "", 500);
        List<AccessSmokeTest.Row> rows = smoke.run(Collections.singletonList(rss()), row -> { });
        assertEquals("timeout", rows.get(0).error); assertEquals(AccessSmokeTest.Outcome.SKIPPED, rows.get(1).outcome);
    }
    @Test public void reportSurvivesActivityRotationAndDoesNotSaveKeysInScreenState() throws Exception {
        CountDownLatch opened = new CountDownLatch(1), release = new CountDownLatch(1);
        SmokeSession smoke = new SmokeSession(Collections.singletonList(rss()), test((url, token, body, api) -> {
            opened.countDown(); try { release.await(3, TimeUnit.SECONDS); } catch (InterruptedException stopped) { Thread.currentThread().interrupt(); }
            return bytes("<rss><channel/></rss>");
        }, name -> ""));
        try (ActivityController<MainActivity> controller = Robolectric.buildActivity(MainActivity.class).setup()) {
            ReflectionHelpers.setField(controller.get(), "smoke", smoke);
            smoke.attach(() -> ReflectionHelpers.callInstanceMethod(controller.get(), "showSmoke"));
            assertTrue(opened.await(3, TimeUnit.SECONDS)); assertTrue(ShadowAlertDialog.getLatestAlertDialog().isShowing());
            controller.recreate(); assertSame(smoke, ReflectionHelpers.getField(controller.get(), "smoke"));
            release.countDown(); Thread worker = ReflectionHelpers.getField(smoke, "worker"); worker.join(3000); shadowOf(Looper.getMainLooper()).idle();
            assertFalse(smoke.running); assertEquals(AccessSmokeTest.Outcome.OK, smoke.rows.get(0).outcome);
            AlertDialog report = ShadowAlertDialog.getLatestAlertDialog(); assertTrue(report.isShowing());
            report.getButton(AlertDialog.BUTTON_POSITIVE).performClick(); shadowOf(Looper.getMainLooper()).idle();
            assertNull(ReflectionHelpers.getField(controller.get(), "smoke"));
        } finally { smoke.close(); release.countDown(); }
    }
    @Test public void manualPollingCountsFailuresSeparatelyFromSuccessfulRequests() throws Exception {
        Store store = Store.get(RuntimeEnvironment.getApplication()); store.replaceFeeds(Arrays.asList(rss(), new Feed("y", "YouTube", "youtube_comments", "dQw4w9WgXcQ", 300, true)));
        PollEngine engine = new PollEngine(RuntimeEnvironment.getApplication(), store, (url, token, body, api) -> bytes("<rss><channel/></rss>"),
                (context, feed, entry) -> { fail("No baseline notifications"); return false; }, name -> "", () -> true);
        PollEngine.Report report = engine.poll(true);
        assertEquals(2, report.checked); assertEquals(1, report.succeeded); assertEquals(1, report.failed); assertEquals(0, report.sent);
    }
}
