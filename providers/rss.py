"""Provider generique pour n'importe quel flux RSS/Atom (feedparser gere
les deux formats de facon transparente). Retourne directement les entrees
feedparser : elles supportent deja .id et .get(), pas besoin de les
adapter via providers.base.Entry."""
import feedparser

LABEL = "RSS/Atom"
SOURCE_HINT = "URL du flux RSS/Atom"
USER_AGENT = "desktop:watch2notif:v1.0 (personal notifier script)"


def fetch_entries(url: str) -> list:
    feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
    if feed.bozo and not feed.entries:
        raise RuntimeError(feed.bozo_exception)
    return feed.entries
