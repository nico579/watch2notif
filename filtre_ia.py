"""Filtre IA facultatif d'une source : avant de notifier une nouvelle entree,
demander a un modele de langage si elle merite de l'etre, selon une consigne
ecrite par l'utilisateur pour cette source.

Exemple : une recherche Reddit sur r/blinkcameras remonte tous les fils qui
parlent de stockage local ou d'abonnement, mais seuls certains sont des
questions auxquelles blink2video repond. Un filtre par mots-cles ne fait pas la
difference entre « comment garder mes clips sans abonnement » et une plainte de
facturation ; un modele qui lit le message, si.

La cle vient de la variable d'environnement ANTHROPIC_API_KEY, comme
GITHUB_TOKEN et YOUTUBE_API_KEY pour les autres sources : jamais dans
config.json ni dans la page. L'API Anthropic se paie a l'usage, a part de tout
abonnement Claude ; avec Haiku, trier quelques dizaines de messages par mois
coute quelques centimes.

Bibliotheque standard seule (urllib), comme les fournisseurs GitHub et YouTube.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

URL = "https://api.anthropic.com/v1/messages"
VERSION_API = "2023-06-01"
MODELE = "claude-haiku-4-5"
VARIABLE_CLE = "ANTHROPIC_API_KEY"
# Un message Reddit ou un commentaire tient largement dans cette limite ; au-dela,
# le debut suffit a juger, et le cout reste borne.
TEXTE_MAX = 4000
DELAI_S = 30

CONSIGNE_SYSTEME = (
    "Tu tries des messages pour une personne qui ne veut etre notifiee que de ceux qui "
    "la concernent. Sa consigne pour cette source est entre les balises <consigne>. "
    "Lis le message, juge s'il correspond a la consigne, et reponds UNIQUEMENT par un "
    "objet JSON sur une ligne : {\"pertinent\": true ou false, \"raison\": \"une phrase "
    "courte, dans la langue de la consigne, qui dit pourquoi\"}. En cas de doute "
    "serieux, reponds true : manquer un message utile est pire qu'une notification de trop."
)


@dataclass
class Verdict:
    pertinent: bool
    raison: str


class FiltreIndisponible(RuntimeError):
    """Pas de verdict (cle absente, reseau, quota, reponse illisible) : l'appelant
    notifie quand meme, en le disant, plutot que de perdre une entree en silence."""


def cle_api() -> str:
    return os.environ.get(VARIABLE_CLE, "").strip()


def _message_utilisateur(consigne: str, entree) -> str:
    texte = str(entree.get("summary") or "")
    # Les flux RSS de Reddit livrent du HTML : les balises ne font que couter.
    texte = re.sub(r"<[^>]+>", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()[:TEXTE_MAX]
    return (
        f"<consigne>\n{consigne.strip()}\n</consigne>\n\n"
        f"<message>\nTitre : {entree.get('title') or ''}\n"
        f"Auteur : {entree.get('author') or ''}\n"
        f"Texte : {texte}\n</message>"
    )


def lire_verdict(texte: str) -> Verdict:
    """Le premier objet JSON de la reponse du modele, avec ses deux champs."""
    trouve = re.search(r"\{.*\}", texte or "", re.S)
    if not trouve:
        raise FiltreIndisponible(f"reponse sans JSON : {texte[:120]!r}")
    try:
        donnees = json.loads(trouve.group(0))
    except json.JSONDecodeError as erreur:
        raise FiltreIndisponible(f"JSON illisible : {erreur}") from erreur
    if not isinstance(donnees, dict) or not isinstance(donnees.get("pertinent"), bool):
        raise FiltreIndisponible(f"champ « pertinent » absent : {trouve.group(0)[:120]!r}")
    return Verdict(donnees["pertinent"], str(donnees.get("raison") or "").strip())


def juger(consigne: str, entree, *, cle: str | None = None, ouvrir=urllib.request.urlopen) -> Verdict:
    """Demande au modele si `entree` (titre, auteur, summary, comme une entree de
    feedparser) correspond a `consigne`. Leve FiltreIndisponible sans verdict."""
    cle = cle if cle is not None else cle_api()
    if not cle:
        raise FiltreIndisponible(f"variable {VARIABLE_CLE} absente")
    corps = json.dumps({
        "model": MODELE,
        "max_tokens": 200,
        "system": CONSIGNE_SYSTEME,
        "messages": [{"role": "user", "content": _message_utilisateur(consigne, entree)}],
    }).encode("utf-8")
    requete = urllib.request.Request(URL, data=corps, method="POST", headers={
        "x-api-key": cle,
        "anthropic-version": VERSION_API,
        "content-type": "application/json",
        "User-Agent": "watch2notif",
    })
    try:
        with ouvrir(requete, timeout=DELAI_S) as reponse:
            donnees = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        try:
            detail = json.loads(erreur.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise FiltreIndisponible(f"API {erreur.code} {detail}".strip()) from erreur
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        raise FiltreIndisponible(str(erreur)) from erreur
    texte = "".join(bloc.get("text", "") for bloc in donnees.get("content") or []
                    if isinstance(bloc, dict) and bloc.get("type") == "text")
    return lire_verdict(texte)
