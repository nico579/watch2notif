package io.github.nico579.watch2notif;

import android.content.Context;
import android.text.Html;
import android.util.Xml;
import org.json.JSONArray;
import org.json.JSONObject;
import org.xmlpull.v1.XmlPullParser;
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

final class Providers {
    private final Context context;
    private final Network.Transport transport;
    Providers(Context context, Network.Transport transport) { this.context = context; this.transport = transport; }

    List<Entry> fetch(Feed feed, String githubToken, String youtubeKey) throws SourceException {
        try {
            switch (feed.kind) {
                case "rss": return rss(transport.request(feed.url, "", null, false), feed.url);
                case "github_issues": return issues(feed.url, githubToken);
                case "github_discussion": return discussion(feed.url, required(githubToken, "github_token"));
                case "github_sponsors": return sponsors(feed.url, required(githubToken, "github_token"));
                case "youtube_comments": return youtube(videoId(feed.url), required(youtubeKey, "youtube_key"));
                default: throw new SourceException("parse");
            }
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("parse"); }
    }

    private static String required(String value, String error) throws SourceException {
        if (value.trim().isEmpty()) throw new SourceException(error);
        return value;
    }

    private static String plain(String value) {
        return Html.fromHtml(value, Html.FROM_HTML_MODE_LEGACY).toString().trim();
    }

    private static String resolve(String base, String value) {
        try { return URI.create(base).resolve(value).toString(); } catch (Exception ignored) { return ""; }
    }

    List<Entry> rss(byte[] document, String sourceUrl) throws SourceException {
        try {
            XmlPullParser parser = Xml.newPullParser();
            parser.setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, true);
            parser.setFeature(XmlPullParser.FEATURE_PROCESS_DOCDECL, false);
            parser.setInput(new ByteArrayInputStream(document), null);
            List<Entry> entries = new ArrayList<>();
            int itemDepth = -1, fieldDepth = -1, authorDepth = -1;
            String field = "", id = "", title = "", author = "", link = "", summary = "", date = "", updated = "";
            StringBuilder text = new StringBuilder();
            List<String> bases = new ArrayList<>(); bases.add(sourceUrl);
            boolean recognized = false, rootClosed = false;
            int event;
            while ((event = parser.nextToken()) != XmlPullParser.END_DOCUMENT) {
                if (event == XmlPullParser.DOCDECL) throw new SourceException("parse");
                if (event == XmlPullParser.START_TAG) {
                    int depth = parser.getDepth();
                    String name = parser.getName(), ns = parser.getNamespace();
                    String parentBase = bases.get(bases.size() - 1);
                    String declaredBase = parser.getAttributeValue("http://www.w3.org/XML/1998/namespace", "base");
                    bases.add(declaredBase == null ? parentBase : resolve(parentBase, declaredBase));
                    if (depth == 1) recognized = "rss".equalsIgnoreCase(name) || "feed".equals(name) || "RDF".equals(name);
                    boolean contentNamespace = ns == null || ns.isEmpty() || ns.equals("http://www.w3.org/2005/Atom")
                            || ns.equals("http://purl.org/rss/1.0/");
                    if (contentNamespace && itemDepth < 0 && ("item".equals(name) || "entry".equals(name))) {
                        itemDepth = depth; id = title = author = link = summary = date = updated = "";
                        String about = parser.getAttributeValue("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "about");
                        if (about != null) id = resolve(bases.get(bases.size() - 1), about);
                    } else if (itemDepth > 0) {
                        if (depth == itemDepth + 1 && "author".equals(name) && contentNamespace) authorDepth = depth;
                        if (fieldDepth < 0 && ((depth == itemDepth + 1 && (contentNamespace
                                || "http://purl.org/dc/elements/1.1/".equals(ns)
                                || "http://purl.org/rss/1.0/modules/content/".equals(ns)))
                                || (authorDepth > 0 && depth == authorDepth + 1 && "name".equals(name)))) {
                            if ("link".equals(name)) {
                                String href = parser.getAttributeValue(null, "href"), rel = parser.getAttributeValue(null, "rel");
                                if (href != null && (rel == null || "alternate".equals(rel))) link = resolve(bases.get(bases.size() - 1), href);
                            }
                            field = name; fieldDepth = depth; text.setLength(0);
                            // Atom author is a container; capture its name child instead.
                            if ("author".equals(name) && "http://www.w3.org/2005/Atom".equals(ns)) fieldDepth = -1;
                        }
                    }
                } else if ((event == XmlPullParser.TEXT || event == XmlPullParser.CDSECT || event == XmlPullParser.ENTITY_REF) && fieldDepth > 0) {
                    if (parser.getText() != null) text.append(parser.getText());
                } else if (event == XmlPullParser.END_TAG) {
                    int depth = parser.getDepth();
                    if (depth == 1) rootClosed = true;
                    if (fieldDepth == depth) {
                        String value = text.toString().trim();
                        switch (field) {
                            case "guid": case "id": if (!value.isEmpty()) id = value; break;
                            case "title": title = plain(value); break;
                            case "author": case "creator": case "name": author = plain(value); break;
                            case "link": if (!value.isEmpty()) link = resolve(bases.get(bases.size() - 1), value); break;
                            case "description": case "summary": summary = plain(value); break;
                            case "content": case "encoded": if (summary.isEmpty()) summary = plain(value); break;
                            case "pubDate": case "published": case "date": date = value; break;
                            case "updated": updated = value; break;
                            default: break;
                        }
                        fieldDepth = -1;
                    }
                    if (authorDepth == depth) authorDepth = -1;
                    if (itemDepth == depth) {
                        long created = timestamp(date); if (created == 0) created = timestamp(updated);
                        entries.add(new Entry(id, title, author, link, summary, created)); itemDepth = -1;
                        if (entries.size() > 2000) throw new SourceException("parse");
                    }
                    if (bases.size() > 1) bases.remove(bases.size() - 1);
                }
            }
            if (!recognized || !rootClosed || itemDepth >= 0) throw new SourceException("parse");
            return entries;
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("parse"); }
    }

    private List<Entry> issues(String repository, String token) throws Exception {
        String raw = new String(transport.request("https://api.github.com/repos/" + repository
                + "/issues?state=open&sort=created&direction=desc&per_page=30", token, null, true), StandardCharsets.UTF_8);
        JSONArray rows = new JSONArray(raw);
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            if (row.has("pull_request")) continue;
            result.add(new Entry(row.getString("id"), str(row, "title", ""), str(row.optJSONObject("user"), "login", "?"),
                    str(row, "html_url", ""), str(row, "body", ""), timestamp(str(row, "created_at", ""))));
        }
        return result;
    }

    private JSONObject graphql(String query, JSONObject variables, String token, boolean nullable) throws Exception {
        String payload = new JSONObject().put("query", query).put("variables", variables).toString();
        JSONObject response = new JSONObject(new String(transport.request("https://api.github.com/graphql", token, payload, true), StandardCharsets.UTF_8));
        JSONArray errors = response.optJSONArray("errors");
        if (errors != null && errors.length() > 0) {
            boolean notFoundOnly = nullable;
            for (int i = 0; i < errors.length(); i++) notFoundOnly &= "NOT_FOUND".equals(errors.getJSONObject(i).optString("type"));
            if (!notFoundOnly) throw new SourceException("graphql");
        }
        JSONObject data = response.optJSONObject("data");
        if (data == null) throw new SourceException("graphql");
        return data;
    }

    private List<Entry> discussion(String source, String token) throws Exception {
        int slash = source.indexOf('/'), hash = source.lastIndexOf('#');
        JSONObject variables = new JSONObject().put("owner", source.substring(0, slash))
                .put("repo", source.substring(slash + 1, hash)).put("number", Integer.parseInt(source.substring(hash + 1)));
        String fields = "id databaseId url bodyText createdAt author { login }";
        JSONObject data = graphql("query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){discussion(number:$number){"
                + "title comments(last:100){nodes{" + fields + " replies(last:100){nodes{" + fields + "}}}}}}}", variables, token, false);
        JSONObject repo = data.optJSONObject("repository"), discussion = repo == null ? null : repo.optJSONObject("discussion");
        if (discussion == null) throw new SourceException("not_found");
        String title = str(discussion, "title", "");
        JSONArray rows = discussion.getJSONObject("comments").getJSONArray("nodes");
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i); result.add(discussionEntry(row, title));
            JSONArray replies = row.getJSONObject("replies").getJSONArray("nodes");
            for (int j = 0; j < replies.length(); j++) result.add(discussionEntry(replies.getJSONObject(j), title));
        }
        return result;
    }

    private Entry discussionEntry(JSONObject row, String title) throws Exception {
        String id = row.isNull("databaseId") ? row.getString("id") : row.getString("databaseId");
        return new Entry(id, title, str(row.optJSONObject("author"), "login", "?"), str(row, "url", ""),
                str(row, "bodyText", ""), timestamp(str(row, "createdAt", "")));
    }

    private List<Entry> sponsors(String login, String token) throws Exception {
        String fields = "sponsorshipsAsMaintainer(first:100,includePrivate:true,orderBy:{field:CREATED_AT,direction:DESC})"
                + "{nodes{id createdAt isOneTimePayment tier{name monthlyPriceInDollars} sponsorEntity{__typename ... on User{login url name} ... on Organization{login url name}}}}";
        JSONObject variables = new JSONObject().put("login", login);
        JSONObject profile = graphql("query($login:String!){user(login:$login){" + fields + "}}", variables, token, true).optJSONObject("user");
        if (profile == null) profile = graphql("query($login:String!){organization(login:$login){" + fields + "}}", variables, token, true).optJSONObject("organization");
        if (profile == null) throw new SourceException("not_found");
        List<Entry> result = new ArrayList<>();
        JSONArray rows = profile.getJSONObject("sponsorshipsAsMaintainer").getJSONArray("nodes");
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i), entity = row.optJSONObject("sponsorEntity"), tier = row.optJSONObject("tier");
            String author = str(entity, "login", "?");
            String title = str(entity, "name", "");
            if (title.trim().isEmpty()) title = author.equals("?") ? context.getString(R.string.anonymous_sponsor) : author;
            String summary = row.optBoolean("isOneTimePayment") ? context.getString(R.string.one_time_donation)
                    : tier != null && !tier.isNull("monthlyPriceInDollars")
                    ? context.getString(R.string.monthly_donation, tier.getString("monthlyPriceInDollars")) : str(tier, "name", "");
            result.add(new Entry(row.getString("id"), title, author, str(entity, "url", ""), summary, timestamp(str(row, "createdAt", ""))));
        }
        return result;
    }

    private JSONObject youtubeGet(String path, String query, String key) throws Exception {
        return new JSONObject(new String(transport.request("https://www.googleapis.com/youtube/v3/" + path + "?" + query
                + "&key=" + URLEncoder.encode(key, "UTF-8"), "", null, true), StandardCharsets.UTF_8));
    }

    private List<Entry> youtube(String video, String key) throws Exception {
        JSONArray videos = youtubeGet("videos", "part=snippet&id=" + video, key).getJSONArray("items");
        String title = videos.length() > 0 ? videos.getJSONObject(0).getJSONObject("snippet").getString("title") : video;
        JSONArray threads = youtubeGet("commentThreads", "part=snippet,replies&order=time&maxResults=100&videoId=" + video, key).getJSONArray("items");
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < threads.length(); i++) {
            JSONObject thread = threads.getJSONObject(i);
            result.add(youtubeEntry(thread.getJSONObject("snippet").getJSONObject("topLevelComment"), video, title));
            JSONObject replies = thread.optJSONObject("replies");
            JSONArray comments = replies == null ? null : replies.optJSONArray("comments");
            if (comments != null) for (int j = 0; j < comments.length(); j++) result.add(youtubeEntry(comments.getJSONObject(j), video, title));
        }
        return result;
    }

    private Entry youtubeEntry(JSONObject row, String video, String title) throws Exception {
        JSONObject snippet = row.getJSONObject("snippet");
        String id = row.getString("id");
        return new Entry(id, title, str(snippet, "authorDisplayName", "?"), "https://www.youtube.com/watch?v=" + video
                + "&lc=" + URLEncoder.encode(id, "UTF-8"), str(snippet, "textOriginal", ""), timestamp(str(snippet, "publishedAt", "")));
    }
}
