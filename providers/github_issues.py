"""Poll GitHub's public REST API for open issues on a repo, instead of
going through an RSS feed (GitHub removed the issues one in 2023). The
REST API stays open for public repos, even without authentication.

Rate limit: 60 requests/hour per IP without a token, 5000/hour with one
(GITHUB_TOKEN environment variable, e.g. `gh auth token`). At a poll
every 60s, a single feed without a token already burns through the whole
limit: plan a longer interval for this kind of feed (per-feed "interval"
field in settings.py).
"""
import json
import os
import urllib.request

from .base import Entry

LABEL = "GitHub issues"
SOURCE_HINT = "owner/repo (ex: nico579/watch2notif)"
API_ROOT = "https://api.github.com"
# Reste large sous la limite non authentifiee de 60 requetes/heure (voir
# le docstring plus haut).
DEFAULT_INTERVAL_SECONDS = 300


def fetch_entries(repo: str) -> list:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "watch2notif",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        f"{API_ROOT}/repos/{repo}/issues?state=open&sort=created&direction=desc&per_page=30",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    entries = []
    for item in data:
        if "pull_request" in item:
            continue  # /issues also returns PRs, keep only actual issues
        body = (item.get("body") or "").strip().replace("\n", " ")
        entries.append(Entry(
            id=str(item["id"]),
            title=item.get("title", "(sans titre)"),
            # "user" est present mais vaut JSON null pour un compte GitHub
            # supprime : item.get("user", {}) renvoie alors None (le defaut
            # ne joue que si la cle est absente), pas {} - d'ou le `or {}`.
            author=(item.get("user") or {}).get("login", "?"),
            link=item.get("html_url", ""),
            summary=body[:150],
            created=item.get("created_at", ""),
        ))
    return entries
