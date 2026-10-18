"""New comments on a repo's issues and pull requests.

github_issues.py only sees a new issue: a comment on an issue it already
knows changes no id and went unnoticed (2026-10-17, two people wrote on
issue #40 of blink2video and nothing rang). One request covers the whole
repo: GitHub lists its comments newest first. The repo owner's own comments
and bots are left out: no point being told what you just wrote, nor every
dependabot remark.
"""
from .base import Entry
from .github_issues import lire_api

LABEL = "GitHub comments"
SOURCE_HINT = "owner/repo (ex: nico579/watch2notif)"
# Meme budget que github_issues.py : une requete par passage.
DEFAULT_INTERVAL_SECONDS = 300


def fetch_entries(repo: str) -> list:
    proprietaire = repo.split("/", 1)[0].casefold()
    data = lire_api(f"/repos/{repo}/issues/comments?sort=created&direction=desc&per_page=30")
    entries = []
    for item in data:
        # "user" vaut JSON null pour un compte GitHub supprime (voir github_issues.py).
        user = item.get("user") or {}
        login = user.get("login", "?")
        if login.casefold() == proprietaire or user.get("type") == "Bot" or login.endswith("[bot]"):
            continue
        # issue_url finit par le numero : les pull requests en ont un aussi.
        numero = (item.get("issue_url") or "").rstrip("/").rsplit("/", 1)[-1]
        entries.append(Entry(
            id=str(item["id"]),
            title=f"#{numero}",
            author=login,
            link=item.get("html_url", ""),
            summary=(item.get("body") or "").strip().replace("\n", " "),
            created=item.get("created_at", ""),
        ))
    return entries
