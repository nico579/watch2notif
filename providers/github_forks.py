"""Activity in a repo's forks: a new fork, or new commits pushed to one.

GitHub tells nobody about it: on 2026-10-17, a fork of blink2video had
carried a doorbell feature and live audio for ten days, and only the
timeline of one issue hinted at it. pushed_at changes on every push, so the
pair (fork, pushed_at) makes a new entry for each bout of activity; a new
fork shows up with the push date it inherited.
"""
from .base import Entry
from .github_issues import lire_api

LABEL = "GitHub forks"
SOURCE_HINT = "owner/repo (ex: nico579/watch2notif)"
# Un fork bouge rarement : une demi-heure suffit, et menage la limite de 60
# requetes/heure sans jeton.
DEFAULT_INTERVAL_SECONDS = 1800


def fetch_entries(repo: str) -> list:
    data = lire_api(f"/repos/{repo}/forks?sort=newest&per_page=100")
    entries = []
    for item in data:
        nom = item.get("full_name", "?")
        pousse = item.get("pushed_at") or ""
        entries.append(Entry(
            id=f"{nom}@{pousse}",
            title=nom,
            author=(item.get("owner") or {}).get("login", "?"),
            link=item.get("html_url", ""),
            summary=(item.get("description") or "").strip(),
            created=pousse,
        ))
    return entries
