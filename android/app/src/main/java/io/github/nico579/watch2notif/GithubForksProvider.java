package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

/** Activity in a repo's forks, twin of providers/github_forks.py: pushed_at changes on every
 *  push, so the pair (fork, pushed_at) makes a new entry for each bout of activity. */
final class GithubForksProvider implements Provider {
    private static final Metadata METADATA = new Metadata("github_forks", R.string.github_forks_label, R.string.github_forks_hint, 1800);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!source.matches("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")) throw new IllegalArgumentException("repo");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String token = request.credential("github");
        String raw = new String(request.transport.request("https://api.github.com/repos/" + feed.url
                + "/forks?sort=newest&per_page=100", token, null, true), StandardCharsets.UTF_8);
        JSONArray rows = new JSONArray(raw);
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            String name = str(row, "full_name", "?"), pushed = str(row, "pushed_at", "");
            result.add(new Entry(name + "@" + pushed, name, str(row.optJSONObject("owner"), "login", "?"),
                    str(row, "html_url", ""), str(row, "description", ""), timestamp(pushed)));
        }
        return result;
    }
}
