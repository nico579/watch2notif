package io.github.nico579.watch2notif;

import android.app.Application;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import java.nio.charset.StandardCharsets;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class ProvidersTest {
    private Providers provider(String document) {
        return new Providers(RuntimeEnvironment.getApplication(), (url, token, body, api) -> document.getBytes(StandardCharsets.UTF_8));
    }

    @Test public void rssReadsGuidHtmlAuthorAndDateWithoutMediaTitleClobbering() throws Exception {
        String document = "<rss xmlns:dc='http://purl.org/dc/elements/1.1/' xmlns:media='http://search.yahoo.com/mrss/'><channel><item>"
                + "<guid>one</guid><title>Actual title</title><media:title>Wrong title</media:title><dc:creator>Alice</dc:creator>"
                + "<link>/article</link><description><![CDATA[<p>Hello &amp; welcome</p>]]></description><pubDate>Wed, 07 Oct 2026 12:00:00 +0000</pubDate></item></channel></rss>";
        Entry entry = provider(document).rss(document.getBytes(StandardCharsets.UTF_8), "https://example.org/feed").get(0);
        assertEquals("one", entry.id); assertEquals("Actual title", entry.title); assertEquals("Alice", entry.author);
        assertEquals("Hello & welcome", entry.summary); assertEquals("https://example.org/article", entry.link); assertTrue(entry.created > 0);
    }

    @Test public void atomResolvesXmlBaseAndUsesAuthorNameAndFallbackId() throws Exception {
        String document = "<feed xmlns='http://www.w3.org/2005/Atom' xml:base='https://example.org/articles/'><entry><title>Hello</title>"
                + "<author><name>Bob</name></author><link rel='self' href='api'/><link href='one'/><summary>Text</summary>"
                + "<published>2026-10-08T10:00:00Z</published></entry></feed>";
        Entry entry = provider(document).rss(document.getBytes(StandardCharsets.UTF_8), "https://example.org/feed").get(0);
        assertEquals("Bob", entry.author); assertEquals("https://example.org/articles/one", entry.link); assertEquals(entry.link, entry.id);
    }

    @Test public void malformedHtmlAndEntityDocumentsAreRejected() {
        for (String document : new String[]{"<html><body>not a feed</body></html>", "<rss><channel>",
                "<!DOCTYPE rss [<!ENTITY secret SYSTEM 'file:///etc/passwd'>]><rss><channel><item><description>&secret;</description></item></channel></rss>"}) {
            try { provider(document).rss(document.getBytes(StandardCharsets.UTF_8), "https://example.org/feed"); fail(document); }
            catch (SourceException expected) { assertEquals("parse", expected.code); }
        }
    }

    @Test public void githubIssuesExcludePullRequestsAndTolerateDeletedAuthors() throws Exception {
        String json = "[{\"id\":1,\"title\":\"Issue\",\"user\":null,\"body\":null},{\"id\":2,\"pull_request\":{}}]";
        List<Entry> entries = provider(json).fetch(new Feed("g", "GitHub", "github_issues", "nico579/watch2notif", 300, true), "", "");
        assertEquals(1, entries.size()); assertEquals("?", entries.get(0).author); assertEquals("1", entries.get(0).id);
    }

    @Test public void discussionRepliesKeepDistinctNodeIdsWhenDatabaseIdsAreNull() throws Exception {
        String json = "{\"data\":{\"repository\":{\"discussion\":{\"title\":\"D\",\"comments\":{\"nodes\":[{\"id\":\"C1\",\"databaseId\":null,\"author\":null,\"replies\":{\"nodes\":[{\"id\":\"R1\",\"databaseId\":null,\"author\":null}]}}]}}}}}";
        List<Entry> entries = provider(json).fetch(new Feed("d", "Discussion", "github_discussion", "nico579/watch2notif#1", 300, true), "test", "");
        assertEquals("C1", entries.get(0).id); assertEquals("R1", entries.get(1).id);
    }

    @Test public void anonymousSponsorsRemainDistinct() throws Exception {
        String json = "{\"data\":{\"user\":{\"sponsorshipsAsMaintainer\":{\"nodes\":[{\"id\":\"s1\",\"sponsorEntity\":null,\"tier\":null},{\"id\":\"s2\",\"sponsorEntity\":null,\"tier\":null}]}}}}";
        List<Entry> entries = provider(json).fetch(new Feed("s", "Sponsors", "github_sponsors", "nico579", 1800, true), "test", "");
        assertEquals(2, entries.size()); assertNotEquals(entries.get(0).id, entries.get(1).id);
    }

    @Test public void youtubeParsesCommonUrlsAndRejectsUnrelatedHosts() {
        for (String url : new String[]{"dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ?t=2", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ"}) assertEquals("dQw4w9WgXcQ", videoId(url));
        try { videoId("https://evil.example/watch?v=dQw4w9WgXcQ"); fail(); } catch (IllegalArgumentException expected) { }
    }

    @Test public void missingProviderKeysNeverIssueRequests() {
        Providers providers = new Providers(RuntimeEnvironment.getApplication(), (u, t, b, a) -> { fail(); return null; });
        try { providers.fetch(new Feed("d", "D", "github_discussion", "nico579/watch2notif#1", 300, true), "", ""); fail(); }
        catch (SourceException expected) { assertEquals("github_token", expected.code); }
    }

    @Test public void verdictParserRejectsNonBooleanDecisions() throws Exception {
        assertFalse(AiFilter.parseVerdict("```json\n{\"pertinent\":false,\"raison\":\"noise\"}\n```").relevant);
        for (String text : new String[]{"yes", "{\"pertinent\":\"false\"}", "{\"raison\":\"no verdict\"}"}) {
            try { AiFilter.parseVerdict(text); fail(); } catch (SourceException expected) { }
        }
    }
}
