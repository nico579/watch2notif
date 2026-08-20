"""Construit le bundle autonome (executable unique watch2notif), dans un
environnement isole jetable.

Pourquoi un environnement dedie a la construction, distinct de celui
d'execution : PyInstaller embarque ce qu'il trouve dans site-packages. Un
venv neuf ne contient que les dependances declarees, et le resultat est
reproductible d'une machine a l'autre.

    python build.py            construit
    python build.py --propre   reconstruit tout depuis zero
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV = BASE_DIR / "build_venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
SORTIE = BASE_DIR / "dist" / "watch2notif"


def executer(commande: list, titre: str) -> None:
    print(f"\n=== {titre}")
    resultat = subprocess.run(commande, cwd=str(BASE_DIR), check=False)
    if resultat.returncode != 0:
        raise SystemExit(f"Echec : {titre}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--propre", action="store_true",
                        help="supprimer l'environnement de construction et les "
                             "sorties precedentes avant de commencer")
    args = parser.parse_args()

    if args.propre:
        for dossier in (VENV, BASE_DIR / "build", BASE_DIR / "dist"):
            if dossier.exists():
                print(f"Suppression de {dossier.name}...")
                shutil.rmtree(dossier, ignore_errors=True)

    if not PYTHON.exists():
        executer([sys.executable, "-m", "venv", str(VENV)],
                 "creation de l'environnement de construction")
    executer([str(PYTHON), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
             "mise a jour de pip")
    executer([str(PYTHON), "-m", "pip", "install", "--quiet", "-r", "requirements.txt", "pyinstaller"],
             "installation des dependances")
    executer([str(PYTHON), "-m", "PyInstaller", "--noconfirm", "--clean",
              str(BASE_DIR / "watch2notif.spec")],
             "construction du bundle")

    suffixe = ".exe" if sys.platform == "win32" else ""
    executable = SORTIE / f"watch2notif{suffixe}"
    if not executable.exists():
        raise SystemExit(f"Executable introuvable : {executable}")

    taille = sum(f.stat().st_size for f in SORTIE.rglob("*") if f.is_file())
    print(f"\nBundle construit : {SORTIE}")
    print(f"  executable  : {executable.name}")
    print(f"  taille      : {taille / 1024 / 1024:.0f} Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
