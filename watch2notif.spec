# Recette de construction du bundle autonome. Voir build.py, qui prepare
# l'environnement isole puis appelle PyInstaller sur ce fichier.
#
# Un seul executable, watch2notif, et un seul toolkit GUI : Qt/PySide6,
# pour la fenetre de reglages (settings.py) comme pour l'icone de tray
# (QSystemTrayIcon dans notifier.py). Melanger Qt avec une lib de tray
# separee (pystray) dans un meme binaire PyInstaller cassait pystray au
# demarrage (shiboken patche `inspect` pour tout le process des que Qt
# fait partie des dependances, meme sans etre importe en premier). --settings
# (cf. le dispatch en bas de notifier.py) ouvre le panneau seul, en
# sous-processus, pour un usage CLI/raccourci ; le tray, lui, l'ouvre
# directement dans le process courant (meme boucle Qt). PyInstaller
# detecte `import settings` meme conditionnel par analyse statique, pas
# besoin de l'ajouter aux hiddenimports ; le hook Qt de
# pyinstaller-hooks-contrib ne bundle que les modules Qt effectivement
# importes (QtCore/QtGui/QtWidgets ici, pas QtWebEngine ni les autres
# poids lourds).
#
# Mode dossier, pas onefile : demarre instantanement, pas de reextraction
# a chaque lancement (notifier tourne en continu au demarrage du systeme).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_ICON = Path(SPECPATH) / "assets" / "watch2notif.png"

# notify_backend.py choisit sa lib de notification a l'execution selon la
# plateforme (win11toast/pync/plyer) : l'analyse statique de PyInstaller ne
# voit que ce qui est importe sans condition, il faut donc lister ici la
# lib propre a la plateforme de construction courante. win11toast s'appuie
# sur winrt, dont les sous-modules natifs ne sont pas tous detectes
# automatiquement.
if sys.platform == "win32":
    NOTIFY_HIDDEN = collect_submodules("winrt") + collect_submodules("win11toast")
elif sys.platform == "darwin":
    NOTIFY_HIDDEN = collect_submodules("pync")
else:
    NOTIFY_HIDDEN = collect_submodules("plyer.platforms")

# pync ne fait qu'appeler le binaire vendorise terminal-notifier.app (dans
# le package pync lui-meme) : c'est une donnee, pas un sous-module Python,
# collect_submodules() ci-dessus ne la voit pas. Sans ca, pync s'importe
# sans erreur a la construction mais echoue au premier notify() une fois
# fige, faute de trouver l'app vendorisee. Non teste ici (pas de Mac) :
# a verifier sur un vrai build macOS.
PYNC_DATAS = collect_data_files("pync") if sys.platform == "darwin" else []

# Ressource VERSIONINFO du binaire Windows. Un PE PyInstaller sans editeur,
# description ni copyright renseignes ressemble statistiquement aux
# echantillons malveillants des jeux d'entrainement de plusieurs moteurs
# antivirus a heuristique ML (constate sur blink2video : faux positifs
# Reddit, confirmes par un scan VirusTotal multi-versions et sur le jumeau
# lidar2map malgre un comportement totalement different). Sans effet hors
# Windows, PyInstaller ignore "version=" sur les autres plateformes.
def _version_info(version: str) -> str:
    parties = (version.split(".") + ["0", "0", "0"])[:3]
    tuple_version = tuple(int(p) for p in parties) + (0,)
    chemin = Path(SPECPATH) / ".version_info.txt"
    chemin.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple_version},
    prodvers={tuple_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'nico579'),
         StringStruct(u'FileDescription', u'watch2notif - notifications de surveillance en tache de fond'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'watch2notif'),
         StringStruct(u'LegalCopyright', u'GPLv3 - nico579'),
         StringStruct(u'OriginalFilename', u'watch2notif.exe'),
         StringStruct(u'ProductName', u'watch2notif'),
         StringStruct(u'ProductVersion', u'{version}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return str(chemin)


def _version() -> str:
    import importlib.util

    charge = importlib.util.spec_from_file_location("update_check", "update_check.py")
    module = importlib.util.module_from_spec(charge)
    charge.loader.exec_module(module)
    return module.VERSION

analysis = Analysis(
    ["notifier.py"],
    pathex=["."],
    hiddenimports=NOTIFY_HIDDEN,
    # Charge a l'execution par notifier.py (tray) et settings.py (icone de
    # fenetre) via RESOURCE_DIR/ICON_FILE (voir notifier.py).
    datas=[(str(APP_ICON), "assets")] + PYNC_DATAS,
    # tkinter n'est plus utilise depuis le passage du panneau de reglage a
    # Qt/PySide6 : l'exclure evite d'embarquer Tcl/Tk pour rien.
    excludes=["tkinter", "PyInstaller", "pytest"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="watch2notif",
    debug=False,
    strip=False,
    upx=False,
    # Pas de fenetre console : c'est un poller de fond, les notifications
    # desktop et le systray sont le seul retour visible attendu (le
    # panneau de reglage, lui, ouvre ses propres fenetres Qt).
    console=False,
    # PNG source portable, converti par PyInstaller en ressource native sur
    # la plateforme de construction (meme mecanisme que blink2video/lidar2map).
    icon=str(APP_ICON),
    version=_version_info(_version()),
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    name="watch2notif",
)

if sys.platform == "darwin":
    # Sans ca, dist/watch2notif/ est un simple dossier Unix : pas d'Info.plist,
    # pas d'identite d'app, Gatekeeper/Finder/LaunchServices ne le
    # reconnaissent pas comme une application macOS. Non teste ici : a
    # verifier sur un vrai build macOS.
    BUNDLE(
        coll,
        name="watch2notif.app",
        icon=str(APP_ICON),
        bundle_identifier="com.nico.watch2notif",
    )
