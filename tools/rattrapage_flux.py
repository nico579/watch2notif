"""Rattrapage ponctuel d'une source RSS par le filtre IA, sur les N derniers jours.

Le filtre IA de watch2notif ne juge que les entrees nouvelles. Ce script, lance a
la main, relit une source (une recherche Reddit, par exemple), garde les entrees
des N derniers jours, les fait juger par le filtre avec la consigne de la source,
et ecrit un rapport Markdown. Il n'envoie aucune notification et ne touche ni a
state/ ni a l'historique : le suivi horaire de watch2notif n'est pas modifie.

    python tools/rattrapage_flux.py --simuler          compte et chiffre, sans appel payant
    python tools/rattrapage_flux.py                    90 jours de r_blinkcameras_questions
    python tools/rattrapage_flux.py --flux CLE --jours 30 --sortie rapport.md

La cle ANTHROPIC_API_KEY est lue dans l'environnement, comme pour le filtre.
Reddit limite les requetes anonymes (HTTP 429 au bout de quelques-unes en
quelques secondes) : une page de 100 entrees remonte souvent plus de trois mois,
la pagination ne s'ouvre que si cette page ne suffit pas.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import data_paths  # noqa: E402
import filtre_ia  # noqa: E402
from providers import rss  # noqa: E402

FLUX_PAR_DEFAUT = "r_blinkcameras_questions"
PAGE = 100                 # maximum de Reddit pour une page de recherche en RSS
PAUSE_ENTRE_PAGES_S = 3.0
# Ordre de grandeur releve sur de vrais messages (Haiku 5.5, effort bas) : environ
# 400 tokens en entree et 90 en sortie, a 0,10 $ et 0,50 $ le million.
COUT_PAR_MESSAGE_USD = (400 * 0.10 + 90 * 0.50) / 1_000_000


def charger_flux(cle: str) -> dict:
    config = json.loads((data_paths.DATA_DIR / "config.json").read_text(encoding="utf-8"))
    for flux in config.get("feeds") or []:
        if flux.get("key") == cle:
            if flux.get("kind", "rss") != "rss":
                raise SystemExit(f"{cle} est de type {flux.get('kind')} : seules les sources RSS sont prises en charge.")
            return flux
    raise SystemExit(f"Source {cle!r} absente de {data_paths.DATA_DIR / 'config.json'}.")


def url_page(url: str, apres: str | None = None) -> str:
    """L'URL de la source avec limit=100 et, pour la page suivante, after=<fullname>."""
    parties = urllib.parse.urlsplit(url)
    requete = [(k, v) for k, v in urllib.parse.parse_qsl(parties.query, keep_blank_values=True)
               if k not in ("limit", "after")]
    requete.append(("limit", str(PAGE)))
    if apres:
        requete.append(("after", apres))
    return urllib.parse.urlunsplit(parties._replace(query=urllib.parse.urlencode(requete)))


def nom_complet(entree) -> str:
    """t3_xxxx, la fin de l'identifiant Reddit (https://www.reddit.com/r/x/t3_xxxx)."""
    return str(entree.id).rstrip("/").rsplit("/", 1)[-1]


def horodatage(entree) -> float | None:
    for cle in ("published_parsed", "updated_parsed"):
        valeur = entree.get(cle)
        if valeur:
            return float(calendar.timegm(valeur))
    return None


def recuperer(url: str, depuis: float, pages_max: int, lire=rss.fetch_entries, pause=time.sleep) -> list:
    """Les entrees de la source jusqu'a `depuis` (timestamp UTC), page apres page.
    S'arrete des qu'une page contient une entree plus ancienne, qu'elle est vide ou
    que pages_max est atteint. Une erreur apres la premiere page garde ce qu'on a."""
    entrees, vues, apres = [], set(), None
    for numero in range(1, pages_max + 1):
        try:
            page = lire(url_page(url, apres))
        except RuntimeError as erreur:
            if numero == 1:
                raise
            print(f"Page {numero} refusee ({erreur}) : on garde les {len(entrees)} entrees deja lues.")
            break
        nouvelles = [e for e in page if str(e.id) not in vues]
        if not nouvelles:
            break
        for entree in nouvelles:
            vues.add(str(entree.id))
        entrees.extend(nouvelles)
        dates = [d for d in map(horodatage, nouvelles) if d is not None]
        if dates and min(dates) < depuis:
            break
        apres = nom_complet(nouvelles[-1])
        if numero < pages_max:
            pause(PAUSE_ENTRE_PAGES_S)
    else:
        print(f"Limite de {pages_max} page(s) atteinte avant d'avoir couvert la periode : "
              f"le rapport s'arrete a la plus ancienne entree lue.")
    return entrees


def dans_la_periode(entrees: list, depuis: float) -> list:
    """Les entrees datees d'au moins `depuis`, de la plus recente a la plus ancienne.
    Une entree sans date est gardee : mieux vaut un doublon qu'un message perdu."""
    gardees = [e for e in entrees if (horodatage(e) is None or horodatage(e) >= depuis)]
    return sorted(gardees, key=lambda e: horodatage(e) or float("inf"), reverse=True)


def liens_deja_notifies() -> set:
    try:
        historique = json.loads((data_paths.DATA_DIR / "notification_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {ligne.get("link") for ligne in historique if isinstance(ligne, dict) and ligne.get("link")}


def juger_tout(entrees: list, consigne: str, juger=filtre_ia.juger, afficher=print) -> list:
    """[(entree, verdict ou None, erreur ou "")]. A la premiere indisponibilite du
    filtre, les entrees restantes ne sont pas jugees : inutile d'attendre N delais."""
    resultats, panne = [], ""
    for numero, entree in enumerate(entrees, 1):
        if panne:
            resultats.append((entree, None, panne))
            continue
        try:
            verdict = juger(consigne, entree)
            resultats.append((entree, verdict, ""))
            afficher(f"[{numero}/{len(entrees)}] {'retenu ' if verdict.pertinent else 'ecarte '}"
                     f"{(entree.get('title') or '')[:70]}")
        except filtre_ia.FiltreIndisponible as erreur:
            panne = str(erreur)
            resultats.append((entree, None, panne))
            afficher(f"[{numero}/{len(entrees)}] filtre indisponible : {panne}. Les entrees restantes ne sont pas jugees.")
    return resultats


def _texte(valeur: str, longueur: int = 0) -> str:
    """Une ligne sans balisage Markdown ni barre verticale, pour une cellule de tableau."""
    valeur = re.sub(r"\s+", " ", str(valeur or "")).strip()
    valeur = valeur.replace("|", "/").replace("[", "(").replace("]", ")")
    return valeur[:longueur - 1] + "…" if longueur and len(valeur) > longueur else valeur


def _date(entree) -> str:
    instant = horodatage(entree)
    return datetime.fromtimestamp(instant, timezone.utc).astimezone().strftime("%Y-%m-%d") if instant else "?"


def rapport(flux: dict, resultats: list, jours: int, deja_notifies: set, maintenant: datetime | None = None) -> str:
    maintenant = maintenant or datetime.now().astimezone()
    retenus = [r for r in resultats if r[1] is not None and r[1].pertinent]
    ecartes = [r for r in resultats if r[1] is not None and not r[1].pertinent]
    non_juges = [r for r in resultats if r[1] is None]
    lignes = [
        f"# Rattrapage de « {flux.get('label', flux.get('key'))} » sur {jours} jours",
        "",
        f"Généré le {maintenant:%Y-%m-%d %H:%M}. {len(resultats)} messages lus : "
        f"{len(retenus)} retenus, {len(ecartes)} écartés, {len(non_juges)} non jugés.",
        "",
        f"Consigne du filtre : {_texte(flux.get('filtre_ia'))}",
        "",
        "Le suivi de watch2notif n'a pas été modifié : rien n'a été notifié ni marqué comme vu.",
        "",
        f"## Retenus ({len(retenus)})",
        "",
    ]
    if retenus:
        lignes += ["| Date | Message | Auteur | Pourquoi | Déjà notifié |", "|---|---|---|---|---|"]
        for entree, verdict, _ in retenus:
            lignes.append(f"| {_date(entree)} | [{_texte(entree.get('title'), 90)}]({entree.get('link', '')}) | "
                          f"{_texte(entree.get('author'), 30)} | {_texte(verdict.raison, 160)} | "
                          f"{'oui' if entree.get('link') in deja_notifies else ''} |")
    else:
        lignes.append("Aucun.")
    lignes += ["", f"## Écartés ({len(ecartes)})", "",
               "À parcourir pour repérer un message que le filtre aurait écarté à tort.", ""]
    for entree, verdict, _ in ecartes:
        lignes.append(f"- {_date(entree)} [{_texte(entree.get('title'), 90)}]({entree.get('link', '')}) : "
                      f"{_texte(verdict.raison, 160)}")
    if non_juges:
        lignes += ["", f"## Non jugés ({len(non_juges)})", "",
                   f"Raison : {_texte(non_juges[0][2])}. À relancer plus tard.", ""]
        for entree, _, _ in non_juges:
            lignes.append(f"- {_date(entree)} [{_texte(entree.get('title'), 90)}]({entree.get('link', '')})")
    return "\n".join(lignes) + "\n"


def main(argv: list | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")      # un titre avec emoji ne doit pas planter la console
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--flux", default=FLUX_PAR_DEFAUT, help="cle de la source dans config.json")
    parseur.add_argument("--jours", type=int, default=90, help="periode a couvrir (defaut 90)")
    parseur.add_argument("--pages-max", type=int, default=3, help="pages de 100 entrees au plus (defaut 3)")
    parseur.add_argument("--consigne", help="remplace la consigne du filtre IA de la source")
    parseur.add_argument("--sortie", type=Path, help="fichier du rapport (defaut : dossier rapports/ des donnees)")
    parseur.add_argument("--simuler", action="store_true", help="lit la source et chiffre, sans appeler l'API payante")
    args = parseur.parse_args(argv)

    flux = charger_flux(args.flux)
    consigne = (args.consigne or flux.get("filtre_ia") or "").strip()
    if not consigne:
        raise SystemExit("Aucune consigne : la source n'a pas de filtre IA, passez --consigne.")
    if not args.simuler and not filtre_ia.cle_api():
        raise SystemExit(f"Variable {filtre_ia.VARIABLE_CLE} absente.")

    depuis = (datetime.now(timezone.utc) - timedelta(days=args.jours)).timestamp()
    try:
        lues = recuperer(flux["url"], depuis, args.pages_max)
    except RuntimeError as erreur:
        raise SystemExit(f"Lecture de la source impossible : {erreur}. Reddit limite les requetes : reessayez dans quelques minutes.")
    entrees = dans_la_periode(lues, depuis)
    plus_ancienne = min((d for d in map(horodatage, entrees) if d), default=None)
    print(f"{len(lues)} entrees lues, {len(entrees)} dans les {args.jours} derniers jours"
          + (f" (la plus ancienne : {datetime.fromtimestamp(plus_ancienne, timezone.utc):%Y-%m-%d})." if plus_ancienne else "."))
    print(f"Cout estime : {len(entrees) * COUT_PAR_MESSAGE_USD * 100:.2f} centimes de dollar (modele {filtre_ia.MODELE}).")
    if args.simuler:
        return 0

    resultats = juger_tout(entrees, consigne)
    sortie = args.sortie or data_paths.DATA_DIR / "rapports" / f"{args.flux}-{datetime.now():%Y-%m-%d}.md"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(rapport({**flux, "filtre_ia": consigne}, resultats, args.jours, liens_deja_notifies()), encoding="utf-8")
    print(f"Rapport : {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
