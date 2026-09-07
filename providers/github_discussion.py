"""Poll GitHub's GraphQL API for comments (and their replies) on a single
Discussion thread. Unlike github_issues.py, GitHub has no REST endpoint for
Discussions at all, and the GraphQL API refuses anonymous requests even for
a public repo: a GITHUB_TOKEN is not optional here (`gh auth token` if the
gh CLI is already logged in).

Source format: "owner/repo#discussion_number", e.g. "fronzbot/blinkpy#1301"
(the number after /discussions/ in the URL).
"""
import json
import os
import re
import urllib.request

from .base import Entry

LABEL = "GitHub discussion replies"
SOURCE_HINT = "owner/repo#numero (ex: fronzbot/blinkpy#1301)"
API_URL = "https://api.github.com/graphql"
# Les reponses a un fil existant sont rares comparees a de nouvelles
# issues sur tout un depot : pas besoin de coller au palier serre de
# github_issues.py.
DEFAULT_INTERVAL_SECONDS = 300

_SOURCE_RE = re.compile(r"^([^/]+)/([^#]+)#(\d+)$")

_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    discussion(number: $number) {
      title
      comments(first: 100) {
        nodes {
          databaseId
          url
          bodyText
          createdAt
          author { login }
          replies(first: 100) {
            nodes {
              databaseId
              url
              bodyText
              createdAt
              author { login }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_entries(source: str) -> list:
    match = _SOURCE_RE.match(source.strip())
    if not match:
        raise ValueError(
            f"source invalide {source!r}, attendu owner/repo#numero (ex: fronzbot/blinkpy#1301)"
        )
    owner, repo, number = match.group(1), match.group(2), int(match.group(3))

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN requis pour ce provider (l'API GraphQL n'accepte pas "
            "les requetes anonymes, meme sur un depot public) ; `gh auth token`"
        )

    payload = json.dumps({
        "query": _QUERY,
        "variables": {"owner": owner, "repo": repo, "number": number},
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "watch2notif",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    if data.get("errors"):
        raise RuntimeError(f"erreurs GraphQL: {data['errors']}")

    discussion = (data.get("data") or {}).get("repository", {}).get("discussion")
    if not discussion:
        raise RuntimeError(f"discussion introuvable pour {source!r}")

    title = discussion.get("title", "(sans titre)")
    entries = []
    for comment in discussion["comments"]["nodes"]:
        entries.append(_to_entry(comment, title))
        for reply in comment["replies"]["nodes"]:
            entries.append(_to_entry(reply, title))
    return entries


def _to_entry(node: dict, discussion_title: str) -> Entry:
    body = (node.get("bodyText") or "").strip().replace("\n", " ")
    return Entry(
        id=str(node["databaseId"]),
        title=discussion_title,
        author=(node.get("author") or {}).get("login", "?"),
        link=node.get("url", ""),
        summary=body[:150],
        created=node.get("createdAt", ""),
    )
