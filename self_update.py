"""Installation transactionnelle des mises à jour de watch2notif.

Le téléchargement vérifié, l'extraction sûre, la préparation du bundle et
l'assistant externe qui remplace le dossier (ou la .app macOS) avec retour
arrière sont ceux de nico579_commons (maj_archive et maj_install), les mêmes
que pour les autres applications. Ce module ne dit que ce qui est propre à
watch2notif : le nom de ses archives pour chaque système, son nom de dossier,
les données à conserver, son service systemd et son agent launchd.
"""

from __future__ import annotations

import platform
import urllib.request
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

InstallLayout = maj_install.Disposition
PreparedUpdate = maj_install.Preparation


class UpdateError(RuntimeError):
    """Erreur exploitable par l'interface pour afficher un message traduit."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def payload(self) -> dict:
        return {"code": self.code, "detail": self.detail}


def _en_update_error(erreur: ErreurMiseAJour) -> UpdateError:
    """Un refus du commun devient l'UpdateError que l'interface sait afficher :
    le même code grossier qu'avant (missing_asset, invalid_asset,
    integrity_failed, download_failed, unsafe_archive, unsafe_install,
    invalid_payload, helper_failed...), le détail en clair."""
    code = "missing_asset" if erreur.code == "asset_absent" else erreur.categorie
    return UpdateError(code, erreur.message("fr"))


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
    raise UpdateError("unsupported_target", f"{system}/{machine}")


def install_layout(
    executable: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    frozen: bool | None = None,
) -> InstallLayout:
    """Décrit le bundle courant et le dossier exact qui peut le remplacer."""
    system = system or platform.system()
    machine = machine or platform.machine()
    asset_name, archive_kind, expected_root = target_for(system, machine)
    try:
        layout = maj_install.disposition(
            APP, asset_name=asset_name, archive_kind=archive_kind,
            racine_attendue=expected_root, executable=executable, systeme=system,
            machine=machine, fige=frozen)
    except ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur
    # Le produit publie un dossier onedir nommé watch2notif. Remplacer le parent
    # de l'exécutable serait destructeur si quelqu'un avait copié exe + _internal
    # directement sur son Bureau ou dans Téléchargements.
    if system != "Darwin" and layout.install_root.name.casefold() != "watch2notif":
        raise UpdateError("unsafe_install", f"dossier non dedie: {layout.install_root}")
    return layout


def can_install_automatically() -> tuple[bool, str]:
    try:
        install_layout()
    except UpdateError as exc:
        return False, exc.code
    return True, ""


def prepare_update(
    info: dict,
    depot: str,
    layout: InstallLayout | None = None,
    opener=urllib.request.urlopen,
    smoke_test: bool = True,
) -> PreparedUpdate:
    """Télécharge, vérifie et extrait le bundle sans toucher à l'installation."""
    layout = layout or install_layout()
    try:
        return maj_install.preparer(APP, info, depot, layout, ouvrir=opener,
                                    auto_test=smoke_test)
    except ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def cleanup_prepared(prepared: PreparedUpdate) -> None:
    maj_install.nettoyer(prepared)


def launch_prepared_update(prepared: PreparedUpdate) -> None:
    """Lance l'assistant, vérifie qu'il est prêt, puis rend la main à l'appelant."""
    try:
        maj_install.lancer(APP, prepared)
    except ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def commit_prepared_update(prepared: PreparedUpdate) -> None:
    """Autorise l'assistant déjà prêt à commencer une fois ce process en train de quitter."""
    try:
        maj_install.valider(prepared)
    except ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def abort_prepared_update(prepared: PreparedUpdate) -> None:
    """Demande à un assistant en attente de renoncer et de nettoyer son dossier."""
    maj_install.annuler(prepared)
