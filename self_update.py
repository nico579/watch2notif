"""Installation transactionnelle des mises à jour de watch2notif.

Le téléchargement vérifié, l'extraction sûre, la préparation du bundle,
l'assistant externe qui remplace le dossier (ou la .app macOS) avec retour
arrière et la conduite de l'installation en fond sont ceux de nico579_commons
(maj_archive et maj_install), les mêmes que pour les autres applications. Ce
module ne dit que ce qui est propre à watch2notif : le nom de ses archives pour chaque système, son nom de dossier,
les données à conserver, son service systemd et son agent launchd.
"""

from __future__ import annotations

import platform
from pathlib import Path

from nico579_commons import maj_install
from nico579_commons.maj_archive import ErreurMiseAJour

MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 30_000
PRESERVED_NAMES = ("config.json", "state", "watch2notif.log", "notification_history.json")

APP = maj_install.Application(
    "watch2notif",
    donnees_preservees=PRESERVED_NAMES,
    noms_toleres=(".watch2notif.lock",),
    unite_systemd="watch2notif.service",
    label_launchd="com.nico.watch2notif",
    fenetre="Hidden",
    taille_archive_max=MAX_ARCHIVE_SIZE,
    taille_extraite_max=MAX_EXTRACTED_SIZE,
    membres_max=MAX_ARCHIVE_MEMBERS,
    agent="watch2notif-updater",
)



def target_for(system: str | None = None, machine: str | None = None) -> tuple[str, str, str]:
    """Renvoie (asset, type d'archive, racine attendue), sans approximation."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()

    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "watch2notif-windows-x86_64.zip", "zip", "watch2notif"
    if system == "Linux" and machine in {"amd64", "x86_64"}:
        return "watch2notif-linux-x86_64.tar.gz", "tar", "watch2notif"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "watch2notif-macos-arm64.zip", "zip", "watch2notif.app"
    raise ErreurMiseAJour("unsupported_target", cible=f"{system}/{machine}")


def install_layout(
    executable: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    frozen: bool | None = None,
) -> maj_install.Disposition:
    """Décrit le bundle courant et le dossier exact qui peut le remplacer.
    Refuse (ErreurMiseAJour) depuis les sources et tout dossier qui n'est pas
    le bundle publié : c'est ce qui décide si l'installation peut s'effectuer
    seule."""
    system = system or platform.system()
    machine = machine or platform.machine()
    asset_name, archive_kind, expected_root = target_for(system, machine)
    layout = maj_install.disposition(
        APP, asset_name=asset_name, archive_kind=archive_kind,
        racine_attendue=expected_root, executable=executable, systeme=system,
        machine=machine, fige=frozen)
    # Le produit publie un dossier onedir nommé watch2notif. Remplacer le parent
    # de l'exécutable serait destructeur si quelqu'un avait copié exe + _internal
    # directement sur son Bureau ou dans Téléchargements.
    if system != "Darwin" and layout.install_root.name.casefold() != "watch2notif":
        raise ErreurMiseAJour("unsafe_install", detail=f"dossier non dedie: {layout.install_root}")
    return layout
