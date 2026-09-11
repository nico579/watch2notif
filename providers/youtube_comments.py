"""Poll YouTube Data API v3 for new comments (and their visible replies) on
a single video. Unlike a channel's uploads, which YouTube exposes as an
Atom feed (https://www.youtube.com/feeds/videos.xml?channel_id=...), there
is no feed at all for comments on a video: this goes through the official
REST API instead (same reasoning as github_issues.py using GitHub's REST
API once the issues RSS feed was retired).

Requires a YouTube Data API key (free): Google Cloud Console -> APIs &
Services -> enable "YouTube Data API v3" -> Credentials -> Create API key
(YOUTUBE_API_KEY environment variable). Quota cost is 1 unit per call
(videos.list + commentThreads.list = 2 units per poll) out of a 10000
units/day free allowance, so even a 60s poll would stay far under the
limit; DEFAULT_INTERVAL_SECONDS below matches the other API-based
providers out of courtesy rather than necessity.

Source format: a video URL (any common form) or a bare 11-char video ID.

Only the first page of comment threads is fetched (newest first via
order=time), same tradeoff as github_issues.py's single page of issues:
plenty for "what's new since last poll", not meant to backfill full
history. Replies are read from the thread response's inline "replies"
part, which YouTube caps at the 5 most recent replies per thread - deeper
threads would need paginating comments.list(parentId=...) separately,
not worth the complexity for a personal notifier.
"""
import json
import os
import re
import urllib.parse
import urllib.request

from .base import Entry

LABEL = "YouTube comments"
SOURCE_HINT = "URL ou ID de la video (ex: https://www.youtube.com/watch?v=6rNqLI9K8Tc)"
API_ROOT = "https://www.googleapis.com/youtube/v3"
DEFAULT_INTERVAL_SECONDS = 300

_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")


def _extract_video_id(source: str) -> str:
    source = source.strip()
    match = _VIDEO_ID_RE.search(source)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", source):
        return source
    raise ValueError(f"source invalide {source!r}, attendu une URL ou un ID de video YouTube")


def _api_get(path: str, params: dict) -> dict:
    url = f"{API_ROOT}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "watch2notif"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_entries(source: str) -> list:
    video_id = _extract_video_id(source)
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY requis pour ce provider (Google Cloud Console : "
            "activer 'YouTube Data API v3' puis Credentials > Create API key)"
        )

    videos = _api_get("videos", {"part": "snippet", "id": video_id, "key": api_key})
    items = videos.get("items", [])
    video_title = items[0]["snippet"]["title"] if items else video_id

    threads = _api_get("commentThreads", {
        "part": "snippet,replies",
        "videoId": video_id,
        "order": "time",
        "maxResults": 100,
        "key": api_key,
    })

    entries = []
    for thread in threads.get("items", []):
        entries.append(_to_entry(thread["snippet"]["topLevelComment"], video_id, video_title))
        for reply in thread.get("replies", {}).get("comments", []):
            entries.append(_to_entry(reply, video_id, video_title))
    return entries


def _to_entry(comment: dict, video_id: str, video_title: str) -> Entry:
    snippet = comment["snippet"]
    body = (snippet.get("textOriginal") or "").strip().replace("\n", " ")
    return Entry(
        id=comment["id"],
        title=video_title,
        author=snippet.get("authorDisplayName", "?"),
        # &lc=<id> fait defiler YouTube jusqu'au commentaire vise.
        link=f"https://www.youtube.com/watch?v={video_id}&lc={comment['id']}",
        summary=body[:150],
        created=snippet.get("publishedAt", ""),
    )
