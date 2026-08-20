"""Poll GitHub's public REST API for open issues on a repo, sans passer
par un flux RSS (GitHub a retire celui des issues en 2023). L'API REST
reste ouverte pour les repos publics, meme sans authentification.

Rate limit : 60 requetes/heure par IP sans token, 5000/heure avec un
token (variable d'environnement GITHUB_TOKEN, ex: `gh auth token`). Avec
un poll toutes les 60s, un seul flux sans token consomme deja toute la
limite : prevoir un intervalle plus long pour ce type de flux (champ
"intervalle" par flux dans settings.py).
"""
import json
import os
import urllib.request

from .base import Entry

LABEL = "GitHub issues"
SOURCE_HINT = "owner/repo (ex: nico579/watch2notif)"
API_ROOT = "https://api.github.com"


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
            continue  # /issues renvoie aussi les PR, on ne garde que les vraies issues
        body = (item.get("body") or "").strip().replace("\n", " ")
        entries.append(Entry(
            id=str(item["id"]),
            title=item.get("title", "(sans titre)"),
            author=item.get("user", {}).get("login", "?"),
            link=item.get("html_url", ""),
            summary=body[:150],
        ))
    return entries
