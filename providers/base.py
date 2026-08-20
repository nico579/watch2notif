"""Common shape for an entry, regardless of the source. Mimics the
feedparser entry API (.id, .get()) so notifier.py only needs to be
written once, with no branching per provider."""


class Entry:
    def __init__(self, id: str, title: str, author: str, link: str, summary: str):
        self.id = id
        self._data = {"title": title, "author": author, "link": link, "summary": summary}

    def get(self, key, default=None):
        return self._data.get(key, default)
