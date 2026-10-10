"""Generic provider for any RSS/Atom feed (feedparser handles both formats
transparently). Returns feedparser entries directly: they already support
.id and .get(), no need to adapt them through providers.base.Entry."""
import socket

import feedparser

LABEL = "RSS/Atom"
SOURCE_HINT = "URL du flux RSS/Atom"
USER_AGENT = "desktop:watch2notif:v1.0 (personal notifier script)"
# Pas de limite de debit cote serveur pour un flux RSS classique.
DEFAULT_INTERVAL_SECONDS = 60

# feedparser.parse() n'expose pas de parametre timeout : sans ca, un flux
# dont le serveur ne repond jamais bloque ce thread indefiniment, et comme
# les sources sont pollees sequentiellement (poll_loop), ca gele aussi
# GitHub et le check de version derriere. Meme valeur que le timeout
# explicite de github_issues.py. Global au process (socket n'offre pas
# mieux), mais les urllib.request.urlopen(..., timeout=...) explicites
# ailleurs dans le code passent leur propre valeur et ne sont pas affectes.
socket.setdefaulttimeout(15)


def fetch_entries(url: str) -> list:
    feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
    # Une reponse HTTP d'erreur (429 de Reddit, 503...) n'est ni "bozo" ni
    # exceptionnelle pour feedparser : elle rend simplement zero entree. Prise
    # pour un flux vide, elle amorcait une source nouvelle sans rien voir,
    # puis tout son contenu etait notifie au cycle suivant. "status" est absent
    # pour un fichier local ou une URL non HTTP.
    status = feed.get("status")
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"HTTP {status}")
    if feed.bozo and not feed.entries:
        raise RuntimeError(feed.bozo_exception)
    return feed.entries
