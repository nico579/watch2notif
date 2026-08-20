"""Generic provider for any RSS/Atom feed (feedparser handles both formats
transparently). Returns feedparser entries directly: they already support
.id and .get(), no need to adapt them through providers.base.Entry."""
import feedparser

LABEL = "RSS/Atom"
SOURCE_HINT = "URL du flux RSS/Atom"
USER_AGENT = "desktop:watch2notif:v1.0 (personal notifier script)"


def fetch_entries(url: str) -> list:
    feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
    if feed.bozo and not feed.entries:
        raise RuntimeError(feed.bozo_exception)
    return feed.entries
