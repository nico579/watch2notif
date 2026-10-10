"""Common shape for an entry, regardless of the source. Mimics the
feedparser entry API (.id, .get()) so notifier.py only needs to be
written once, with no branching per provider.

summary carries the whole text, never pre-truncated: notifier.notify()
shortens it for display, and filtre_ia.py reads up to TEXTE_MAX
characters of it (the providers used to cut it at [:150], which left the
AI filter judging a GitHub or YouTube message on its first line only)."""


class Entry:
    def __init__(self, id: str, title: str, author: str, link: str, summary: str, created: str = ""):
        self.id = id
        self._data = {
            "title": title,
            "author": author,
            "link": link,
            "summary": summary,
            "created": created,
        }

    def get(self, key, default=None):
        return self._data.get(key, default)
