"""Forme commune d'une entree, quelle que soit la source. Imite l'API des
entrees feedparser (.id, .get()) pour que notifier.py reste ecrit une
seule fois, sans branchement selon le provider."""


class Entry:
    def __init__(self, id: str, title: str, author: str, link: str, summary: str):
        self.id = id
        self._data = {"title": title, "author": author, "link": link, "summary": summary}

    def get(self, key, default=None):
        return self._data.get(key, default)
