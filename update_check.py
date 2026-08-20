"""Verifie si une nouvelle version est publiee sur GitHub, sans rien
telecharger ni remplacer (contrairement au maj.py de blink2video) :
watch2notif tourne en tache de fond au demarrage du systeme, se
remplacer soi-meme en cours d'execution est un risque hors de propos
pour ce projet. On se contente de prevenir via le systray, l'utilisateur
va chercher la nouvelle version lui-meme sur la page de release.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.1"
DEPOT = "nico579/watch2notif"
# Prefixe par un point : state/ contient aussi un fichier par source
# (nomme d'apres sa cle, cf notifier.state_file), et slugify() ne peut
# jamais produire de point en tete - une source nommee "Update Check" ne
# collisionnera donc jamais avec ce cache interne.
CACHE_FILE_NAME = ".update_check.json"
# Six heures : une version ne sort pas plus souvent, pas la peine
# d'interroger GitHub a chaque cycle de poll (meme intervalle que
# blink2video/maj.py, pas de raison de diverger).
FRAICHEUR = 6 * 3600


def _numeros(version: str) -> tuple:
    """« v0.5.3 » devient (0, 5, 3), comparable a un autre tuple (une
    comparaison de chaines rangerait 0.5.10 avant 0.5.9)."""
    propre = version.strip().lstrip("vV")
    morceaux = []
    for part in propre.split("."):
        chiffres = "".join(c for c in part if c.isdigit())
        morceaux.append(int(chiffres) if chiffres else 0)
    return tuple(morceaux)


def _write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _interroger() -> dict:
    requete = urllib.request.Request(
        f"https://api.github.com/repos/{DEPOT}/releases/latest",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"watch2notif/{VERSION}"},
    )
    with urllib.request.urlopen(requete, timeout=10) as reponse:
        return json.loads(reponse.read())


def disponible(base_dir: Path, force: bool = False) -> dict:
    """La version publiee si elle est plus recente que VERSION, sinon {}.

    Cache dans base_dir/state/ : evite d'interroger GitHub a chaque appel,
    et sert encore hors ligne (une mise a jour signalee hier reste vraie)."""
    cache_file = base_dir / "state" / CACHE_FILE_NAME
    cache = {}
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}

    age = time.time() - float(cache.get("verifie") or 0)
    if force or age > FRAICHEUR or not cache:
        # Horodatage pose avant la requete, succes ou echec : sinon un
        # GitHub indisponible ferait retenter a CHAQUE appel (poll_loop
        # rappelle disponible() toutes les 5s) au lieu d'attendre FRAICHEUR,
        # martelant l'API a chaque cycle.
        tentative = time.time()
        try:
            release = _interroger()
            cache = {
                "verifie": tentative,
                "version": str(release.get("tag_name") or "").lstrip("vV"),
                "page": release.get("html_url"),
            }
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            # Hors ligne ou GitHub indisponible : pas grave, on garde le
            # reste du cache (version/page connues), seul l'horodatage bouge.
            cache = {**cache, "verifie": tentative}
        try:
            cache_file.parent.mkdir(exist_ok=True)
            _write_json_atomic(cache_file, cache)
        except OSError:
            pass

    version_distante = cache.get("version") or ""
    if version_distante and _numeros(version_distante) > _numeros(VERSION):
        return {"version": version_distante, "page": cache.get("page")}
    return {}
