"""Essai manuel du filtre IA sur les vrais messages d'un flux, pour regler une consigne
avant de la confier a watch2notif. Rien n'est notifie ni enregistre : le script lit le
flux, demande le verdict pour chaque entree et l'affiche.

    set ANTHROPIC_API_KEY=sk-ant-...            (Windows ; export sous Linux et macOS)
    python tests/essai_filtre_ia.py URL_DU_FLUX "Consigne en langage courant"

Chaque entree coute un appel a l'API (Claude Haiku, quelques dixiemes de centime pour
un flux Reddit de 25 messages). Ce n'est pas un test automatique : unittest ne le
decouvre pas (son nom ne commence pas par « test »).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import filtre_ia  # noqa: E402
from providers import rss  # noqa: E402


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    url, consigne = argv[1], argv[2]
    entrees = rss.fetch_entries(url)
    print(f"{len(entrees)} entree(s) dans le flux.\n")
    retenues = 0
    for entree in entrees:
        titre = entree.get("title", "")
        try:
            verdict = filtre_ia.juger(consigne, entree)
        except filtre_ia.FiltreIndisponible as erreur:
            print(f"  ?  {titre}\n     filtre indisponible : {erreur}")
            continue
        retenues += verdict.pertinent
        print(f"  {'OUI' if verdict.pertinent else 'non'}  {titre}\n       {verdict.raison}")
    print(f"\n{retenues} entree(s) retenue(s) sur {len(entrees)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
