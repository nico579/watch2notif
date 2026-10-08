package io.github.nico579.watch2notif;

import android.app.Application;
import android.content.Context;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import static io.github.nico579.watch2notif.Models.*;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class ProviderRegistryTest {
    private Context context() { return RuntimeEnvironment.getApplication(); }
    private byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private Feed feed(String kind, String source) { return new Feed("test", "Test", kind, source, defaultInterval(kind), true); }

    private Provider stub(String kind) {
        return new Provider() {
            @Override public Metadata metadata() { return new Metadata(kind, R.string.rss_label, R.string.rss_hint, 60); }
            @Override public void validateSource(String source) { }
            @Override public List<Entry> fetch(Feed feed, Request request) { return List.of(); }
        };
    }

    @Test public void builtinsKeepPortableIdsAndDriveEditorMetadataAndImportDefaults() throws Exception {
        String[] kinds = {"rss", "github_issues", "github_discussion", "github_sponsors", "youtube_comments"};
        String[] sources = {"https://example.org/feed", "nico579/watch2notif", "nico579/watch2notif#1", "nico579", "dQw4w9WgXcQ"};
        int[] intervals = {60, 300, 300, 1800, 300};
        assertArrayEquals(kinds, KINDS);
        assertEquals(kinds.length, ProviderRegistry.BUILTINS.all().size());
        Set<Class<?>> implementations = new HashSet<>();
        for (int i = 0; i < kinds.length; i++) {
            Provider provider = ProviderRegistry.BUILTINS.require(kinds[i]);
            Provider.Metadata metadata = provider.metadata();
            assertEquals(i, kindIndex(kinds[i])); assertEquals(intervals[i], defaultInterval(kinds[i]));
            assertEquals(metadata.label, LABELS[i]); assertEquals(metadata.hint, HINTS[i]);
            assertFalse(context().getString(metadata.label).isEmpty()); assertFalse(context().getString(metadata.hint).isEmpty());
            implementations.add(provider.getClass());
            Feed imported = Feed.fromJson(new JSONObject().put("kind", kinds[i]).put("url", sources[i]), 17, true);
            assertEquals(intervals[i], imported.interval); assertEquals(kinds[i], imported.json().getString("kind"));
        }
        assertEquals(5, implementations.size());
    }

    @Test public void registryRejectsAmbiguousIdsAndCannotBeMutated() {
        for (Provider[] providers : new Provider[][]{ {}, {stub("")}, {stub(" ")}, {stub("rss"), stub("rss")} }) {
            try { new ProviderRegistry(providers); fail(); } catch (IllegalArgumentException expected) { }
        }
        try { ProviderRegistry.BUILTINS.all().clear(); fail(); } catch (UnsupportedOperationException expected) { }
        String[] snapshot = ProviderRegistry.BUILTINS.kinds(); snapshot[0] = "changed";
        assertEquals("rss", ProviderRegistry.BUILTINS.kinds()[0]);
        assertEquals(-1, kindIndex("unknown"));
        try { defaultInterval("unknown"); fail(); } catch (IllegalArgumentException expected) { }
    }

    @Test public void feedValidationIsOwnedByEachRegisteredProvider() {
        String[][] invalid = {{"rss", "file:///private"}, {"github_issues", "owner"}, {"github_discussion", "owner/repo#0"},
                {"github_sponsors", "owner/repo"}, {"youtube_comments", "https://evil.example/watch?v=dQw4w9WgXcQ"}};
        for (String[] source : invalid) {
            try { ProviderRegistry.BUILTINS.require(source[0]).validateSource(source[1]); fail(source[0]); }
            catch (IllegalArgumentException expected) { }
            try { feed(source[0], source[1]); fail(source[0]); } catch (IllegalArgumentException expected) { }
        }
    }

    @Test public void facadeDispatchesRegisteredImplementationAndInjectedServices() throws Exception {
        List<String> calls = new ArrayList<>();
        Network.Transport network = (url, token, body, api) -> { calls.add(url); return bytes("provider response"); };
        Provider custom = new Provider() {
            @Override public Metadata metadata() { return new Metadata("rss", R.string.rss_label, R.string.rss_hint, 60); }
            @Override public void validateSource(String source) { calls.add("validate:" + source); }
            @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
                assertSame(context(), request.context); assertSame(network, request.transport);
                String secret = request.requiredCredential("custom", "custom_missing");
                String response = new String(request.transport.request(feed.url, secret, null, false), StandardCharsets.UTF_8);
                return List.of(new Entry("custom-id", response, "", feed.url, "", 0));
            }
        };
        Providers facade = new Providers(context(), network, new ProviderRegistry(custom));
        List<Entry> result = facade.fetch(feed("rss", "https://example.org/feed"), name -> { assertEquals("custom", name); return "test-value"; });
        assertEquals("custom-id", result.get(0).id); assertEquals("provider response", result.get(0).title);
        assertEquals(List.of("validate:https://example.org/feed", "https://example.org/feed"), calls);
    }

    @Test public void providersReadOnlyTheirOwnCredentialsAndRequiredKeysFailBeforeNetwork() throws Exception {
        List<String> credentials = new ArrayList<>();
        Providers rss = new Providers(context(), (u, t, b, a) -> { assertEquals("", t); assertFalse(a); return bytes("<rss><channel/></rss>"); });
        assertTrue(rss.fetch(feed("rss", "https://example.org/feed"), name -> { fail("RSS must not read credentials"); return ""; }).isEmpty());
        Providers issues = new Providers(context(), (u, t, b, a) -> { assertEquals("", t); assertTrue(a); return bytes("[]"); });
        assertTrue(issues.fetch(feed("github_issues", "owner/repo"), name -> { credentials.add(name); return ""; }).isEmpty());
        assertEquals(List.of("github"), credentials);
        String[][] required = {{"github_discussion", "owner/repo#1", "github", "github_token"},
                {"github_sponsors", "owner", "github", "github_token"}, {"youtube_comments", "dQw4w9WgXcQ", "youtube", "youtube_key"}};
        Providers guarded = new Providers(context(), (u, t, b, a) -> { fail("Missing key must not issue a request"); return null; });
        for (String[] source : required) {
            try { guarded.fetch(feed(source[0], source[1]), name -> { assertEquals(source[2], name); return " "; }); fail(); }
            catch (SourceException expected) { assertEquals(source[3], expected.code); }
        }
    }

    @Test public void facadePreservesSanitizedHttpAndCredentialErrors() {
        Feed github = feed("github_issues", "owner/repo");
        Providers failedHttp = new Providers(context(), (u, t, b, a) -> { throw new SourceException("http", 429); });
        try { failedHttp.fetch(github, name -> "test"); fail(); }
        catch (SourceException expected) { assertEquals("http", expected.code); assertEquals(429, expected.httpStatus); }
        Providers noNetwork = new Providers(context(), (u, t, b, a) -> { fail(); return null; });
        try { noNetwork.fetch(github, name -> { throw new IOException("private-key-details"); }); fail(); }
        catch (SourceException expected) { assertEquals("storage", expected.getMessage()); }
        try { noNetwork.fetch(github, name -> { throw new IllegalStateException("private-key-details"); }); fail(); }
        catch (SourceException expected) { assertEquals("network", expected.getMessage()); }
        Providers malformed = new Providers(context(), (u, t, b, a) -> bytes("private-key-details"));
        try { malformed.fetch(github, name -> "test"); fail(); }
        catch (SourceException expected) { assertEquals("parse", expected.getMessage()); }
    }

    @Test public void sponsorsKeepOrganizationFallbackAndGraphqlWindow() throws Exception {
        List<String> queries = new ArrayList<>();
        Providers sponsors = new Providers(context(), (url, token, body, api) -> {
            assertEquals("https://api.github.com/graphql", url); assertEquals("github-test", token); assertTrue(api);
            try {
                JSONObject payload = new JSONObject(body);
                assertEquals("some-org", payload.getJSONObject("variables").getString("login"));
                String query = payload.getString("query"); queries.add(query);
                assertTrue(query.contains("first:100,includePrivate:true"));
                return query.contains("user(login:") ? bytes("{\"errors\":[{\"type\":\"NOT_FOUND\"}],\"data\":{\"user\":null}}")
                        : bytes("{\"data\":{\"organization\":{\"sponsorshipsAsMaintainer\":{\"nodes\":[]}}}}");
            } catch (Exception failure) { throw new AssertionError(failure); }
        });
        assertTrue(sponsors.fetch(feed("github_sponsors", "some-org"), name -> "github-test").isEmpty());
        assertEquals(2, queries.size()); assertTrue(queries.get(1).contains("organization(login:"));
    }

    @Test public void youtubeKeepsCommentAndReplyParsingAndWindow() throws Exception {
        List<String> urls = new ArrayList<>();
        Providers youtube = new Providers(context(), (url, token, body, api) -> {
            urls.add(url); assertEquals("", token); assertTrue(api); assertNull(body);
            assertTrue(url.endsWith("&key=test+key"));
            if (url.contains("/videos?")) return bytes("{\"items\":[{\"snippet\":{\"title\":\"Video\"}}]}");
            assertTrue(url.contains("maxResults=100&videoId=dQw4w9WgXcQ"));
            return bytes("{\"items\":[{\"snippet\":{\"topLevelComment\":{\"id\":\"C1\",\"snippet\":{\"textOriginal\":\"Hello\"}}},"
                    + "\"replies\":{\"comments\":[{\"id\":\"R1\",\"snippet\":{\"authorDisplayName\":\"Bob\",\"textOriginal\":\"Reply\"}}]}}]}");
        });
        List<Entry> entries = youtube.fetch(feed("youtube_comments", "https://youtu.be/dQw4w9WgXcQ"), name -> { assertEquals("youtube", name); return "test key"; });
        assertEquals(2, urls.size()); assertEquals(2, entries.size()); assertEquals("C1", entries.get(0).id);
        assertEquals("Video", entries.get(0).title); assertEquals("R1", entries.get(1).id); assertEquals("Bob", entries.get(1).author);
    }
}
