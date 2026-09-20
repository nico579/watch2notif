# Recette de construction du bundle autonome. Voir build.py, qui prepare
# l'environnement isole puis appelle PyInstaller sur ce fichier.
#
# Un seul executable, watch2notif. Reglages et historique sont une page
# web (gui/), servie en HTTP local par _serve_web.py et ouverte dans le
# navigateur par defaut - plus de fenetre Qt separee. L'icone de zone de
# notification utilise pystray (meme bibliotheque que lidar2map et
# blink2video) : plus de PySide6/QSystemTrayIcon dans ce projet, donc plus
# du tout du conflit shiboken/pystray qui empechait de melanger les deux
# dans un meme binaire PyInstaller (`inspect` patche pour tout le process
# des que Qt fait partie des dependances). --settings (bas de notifier.py)
# ouvre le navigateur sur l'instance en cours plutot qu'un panneau separe.
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

# Page de reglages/historique (index.html/app.js/style.css), servie telle
# quelle en HTTP local par _serve_web.py (send_static) : ce sont des
# fichiers statiques, jamais importes par du code Python, PyInstaller ne
# les detecte donc pas tout seul (meme situation que gui/ dans
# lidar2map.spec).
GUI_DIR = Path(SPECPATH) / "gui"
GUI_DATAS = [(str(f), "gui") for f in sorted(GUI_DIR.glob("*")) if f.is_file()]

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
    # Icone chargee a l'execution par pystray (RESOURCE_DIR/ICON_FILE, voir
    # notifier.py) ; gui/ est la page de reglages/historique (voir GUI_DATAS
    # ci-dessus).
    datas=[(str(APP_ICON), "assets")] + GUI_DATAS + PYNC_DATAS,
    # tkinter : jamais importe par ce projet (page web, pas de GUI native) ;
    # l'exclure evite d'embarquer Tcl/Tk pour rien si un hook tiers le
    # detectait par erreur.
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
    # desktop et l'icone de zone de notification sont le seul retour
    # visible attendu (les reglages/l'historique s'ouvrent dans le
    # navigateur par defaut du systeme, pas une fenetre a part).
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
