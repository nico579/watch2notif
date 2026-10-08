package io.github.nico579.watch2notif;

import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;

final class YoutubeCommentsProvider implements Provider {
    private static final Metadata METADATA = new Metadata("youtube_comments", R.string.youtube_comments_label, R.string.youtube_comments_hint, 300);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) { videoId(source); }

    @Override public List<Entry> fetch(Feed feed, Request request) throws Exception {
        String video = videoId(feed.url), key = request.requiredCredential("youtube", "youtube_key");
        JSONArray videos = get(request, "videos", "part=snippet&id=" + video, key).getJSONArray("items");
        String title = videos.length() > 0 ? videos.getJSONObject(0).getJSONObject("snippet").getString("title") : video;
        JSONArray threads = get(request, "commentThreads", "part=snippet,replies&order=time&maxResults=100&videoId=" + video, key).getJSONArray("items");
        List<Entry> result = new ArrayList<>();
        for (int i = 0; i < threads.length(); i++) {
            JSONObject thread = threads.getJSONObject(i);
            result.add(entry(thread.getJSONObject("snippet").getJSONObject("topLevelComment"), video, title));
            JSONObject replies = thread.optJSONObject("replies");
            JSONArray comments = replies == null ? null : replies.optJSONArray("comments");
            if (comments != null) for (int j = 0; j < comments.length(); j++) result.add(entry(comments.getJSONObject(j), video, title));
        }
        return result;
    }

    private JSONObject get(Request request, String path, String query, String key) throws Exception {
        return new JSONObject(new String(request.transport.request("https://www.googleapis.com/youtube/v3/" + path + "?" + query
                + "&key=" + URLEncoder.encode(key, "UTF-8"), "", null, true), StandardCharsets.UTF_8));
    }

    private Entry entry(JSONObject row, String video, String title) throws Exception {
        JSONObject snippet = row.getJSONObject("snippet");
        String id = row.getString("id");
        return new Entry(id, title, str(snippet, "authorDisplayName", "?"), "https://www.youtube.com/watch?v=" + video
                + "&lc=" + URLEncoder.encode(id, "UTF-8"), str(snippet, "textOriginal", ""), timestamp(str(snippet, "publishedAt", "")));
    }
}
