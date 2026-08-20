"""Verifie si une nouvelle version est publiee sur GitHub, sans rien
telecharger ni remplacer (contrairement au maj.py de blink2video) :
watch2notif tourne en tache de fond au demarrage du systeme, se
remplacer soi-meme en cours d'execution est un risque hors de propos
pour ce projet. On se contente de prevenir via le systray, l'utilisateur
va chercher la nouvelle version lui-meme sur la page de release.
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
DEPOT = "nico579/watch2notif"
CACHE_FILE_NAME = "update_check.json"
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
        try:
            release = _interroger()
            cache = {
                "verifie": time.time(),
                "version": str(release.get("tag_name") or "").lstrip("vV"),
                "page": release.get("html_url"),
            }
            try:
                cache_file.parent.mkdir(exist_ok=True)
                cache_file.write_text(json.dumps(cache), encoding="utf-8")
            except OSError:
                pass
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
            # Hors ligne ou GitHub indisponible : pas grave, on garde le cache.
            pass

    version_distante = cache.get("version") or ""
    if version_distante and _numeros(version_distante) > _numeros(VERSION):
        return {"version": version_distante, "page": cache.get("page")}
    return {}
