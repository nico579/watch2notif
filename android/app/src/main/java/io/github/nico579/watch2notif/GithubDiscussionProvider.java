package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;
import static io.github.nico579.watch2notif.ProviderSupport.*;

final class GithubDiscussionProvider implements Provider {
    private static final Metadata METADATA = new Metadata("github_discussion", R.string.github_discussion_label, R.string.github_discussion_hint, 300);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!source.matches("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]{0,8}")) throw new IllegalArgumentException("discussion");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String source = feed.url, token = request.requiredCredential("github", "github_token");
        int slash = source.indexOf('/'), hash = source.lastIndexOf('#');
        JSONObject variables = new JSONObject().put("owner", source.substring(0, slash))
                .put("repo", source.substring(slash + 1, hash)).put("number", Integer.parseInt(source.substring(hash + 1)));
        String fields = "id databaseId url bodyText createdAt author { login }";
        JSONObject data = graphql(request, "query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){discussion(number:$number){"
                + "title comments(last:100){nodes{" + fields + " replies(last:100){nodes{" + fields + "}}}}}}}", variables, token, false);
        JSONObject repo = data.optJSONObject("repository"), discussion = repo == null ? null : repo.optJSONObject("discussion");
        if (discussion == null) throw new SourceException("not_found");
        String title = str(discussion, "title", "");
        JSONArray rows = discussion.getJSONObject("comments").getJSONArray("nodes");
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i); result.add(entry(row, title));
            JSONArray replies = row.getJSONObject("replies").getJSONArray("nodes");
            for (int j = 0; j < replies.length(); j++) result.add(entry(replies.getJSONObject(j), title));
        }
        return result;
    }

    private Entry entry(JSONObject row, String title) throws Exception {
        String id = row.isNull("databaseId") ? row.getString("id") : row.getString("databaseId");
        return new Entry(id, title, str(row.optJSONObject("author"), "login", "?"), str(row, "url", ""),
                str(row, "bodyText", ""), timestamp(str(row, "createdAt", "")));
    }
}
