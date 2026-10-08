package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

final class GithubIssuesProvider implements Provider {
    private static final Metadata METADATA = new Metadata("github_issues", R.string.github_issues_label, R.string.github_issues_hint, 300);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!source.matches("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")) throw new IllegalArgumentException("repo");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String token = request.credential("github");
        String raw = new String(request.transport.request("https://api.github.com/repos/" + feed.url
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
}
