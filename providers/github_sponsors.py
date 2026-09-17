"""Poll GitHub's GraphQL API for new sponsors on a GitHub Sponsors profile.
GitHub sends no notification (email or otherwise) when someone new
sponsors you - see https://github.com/orgs/community/discussions/41675 -
so this is the only way to find out without checking the dashboard by
hand. Same GraphQL-only situation as github_discussion.py, but this one
additionally needs the `read:user` scope on top of the usual token: the
sponsorship's own `id` (the stable identifier used for a sponsor who opted
to stay anonymous, where sponsorEntity comes back null) sits behind that
scope, not just behind having a token at all like github_issues.py.

Source format: the GitHub login (user or organization) whose sponsors to
watch, e.g. "nico579" - almost always your own account.
"""
import json
import os
import urllib.request

from .base import Entry

LABEL = "GitHub Sponsors"
SOURCE_HINT = "login GitHub (ex: nico579)"
API_URL = "https://api.github.com/graphql"
# Un nouveau sponsor est rare, moins frequent qu'une reponse de discussion :
# pas besoin de coller a l'intervalle de github_discussion.py.
DEFAULT_INTERVAL_SECONDS = 1800

_QUERY = """
query($login: String!) {
  user(login: $login) {
    sponsorshipsAsMaintainer(first: 100, includePrivate: true, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        id
        createdAt
        isOneTimePayment
        tier { name monthlyPriceInDollars }
        sponsorEntity {
          __typename
          ... on User { login url name }
          ... on Organization { login url name }
        }
      }
    }
  }
}
"""


def fetch_entries(source: str) -> list:
    login = source.strip()
    if not login:
        raise ValueError(
            "source invalide : indiquez un identifiant GitHub (ex: nico579)"
        )

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN requis pour ce provider, avec le scope read:user en "
            "plus des scopes habituels (l'API GraphQL n'accepte pas les "
            "requetes anonymes, et l'id de sponsorship - necessaire pour un "
            "sponsor reste anonyme - est derriere ce scope precis)"
        )

    payload = json.dumps({
        "query": _QUERY,
        "variables": {"login": login},
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

    user = (data.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"utilisateur GitHub introuvable : {login!r}")

    return [_to_entry(node) for node in user["sponsorshipsAsMaintainer"]["nodes"]]


def _to_entry(node: dict) -> Entry:
    entity = node.get("sponsorEntity") or {}
    # sponsorEntity vaut null pour un sponsor qui a choisi l'anonymat : rien
    # a afficher ni a lier, mais node["id"] (le sponsorship, pas l'entite)
    # reste present et distinct pour chacun, donc jamais de collision entre
    # deux sponsors anonymes successifs.
    login = entity.get("login")
    nom = entity.get("name") or login or "sponsor anonyme"
    tier = node.get("tier") or {}
    if node.get("isOneTimePayment"):
        montant = "don ponctuel"
    elif tier.get("monthlyPriceInDollars") is not None:
        montant = f"{tier['monthlyPriceInDollars']} $/mois"
    else:
        montant = tier.get("name") or ""
    return Entry(
        id=str(node["id"]),
        title=nom,
        author=login or "?",
        link=entity.get("url", ""),
        summary=montant,
        created=node.get("createdAt", ""),
    )
