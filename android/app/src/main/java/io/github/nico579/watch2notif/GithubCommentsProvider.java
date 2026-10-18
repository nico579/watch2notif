package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import static io.github.nico579.watch2notif.Models.*;

/** New comments on a repo's issues and pull requests, twin of providers/github_comments.py:
 *  the repo owner's own comments and bots are left out. */
final class GithubCommentsProvider implements Provider {
    private static final Metadata METADATA = new Metadata("github_comments", R.string.github_comments_label, R.string.github_comments_hint, 300);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!source.matches("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")) throw new IllegalArgumentException("repo");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String token = request.credential("github");
        String raw = new String(request.transport.request("https://api.github.com/repos/" + feed.url
                + "/issues/comments?sort=created&direction=desc&per_page=30", token, null, true), StandardCharsets.UTF_8);
        String owner = feed.url.substring(0, feed.url.indexOf('/')).toLowerCase(Locale.ROOT);
        JSONArray rows = new JSONArray(raw);
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            JSONObject user = row.optJSONObject("user");
            String login = str(user, "login", "?");
            if (login.toLowerCase(Locale.ROOT).equals(owner) || "Bot".equals(str(user, "type", "")) || login.endsWith("[bot]")) continue;
            String issue = str(row, "issue_url", "");
            result.add(new Entry(row.getString("id"), "#" + issue.substring(issue.lastIndexOf('/') + 1), login,
                    str(row, "html_url", ""), str(row, "body", ""), timestamp(str(row, "created_at", ""))));
        }
        return result;
    }
}
