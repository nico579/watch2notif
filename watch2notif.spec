# Recette de construction du bundle autonome. Voir build.py, qui prepare
# l'environnement isole puis appelle PyInstaller sur ce fichier.
#
# Deux executables partagent un seul dossier dist/watch2notif : watch2notif
# (le poller de fond, notifier.py) et watch2notif-settings (le panneau de
# reglage tkinter, settings.py). MERGE() evite de dupliquer les
# dependances communes entre les deux.
#
# Mode dossier, pas onefile : demarre instantanement, pas de reextraction
# a chaque lancement (notifier tourne en continu au demarrage du systeme).

import sys

from PyInstaller.utils.hooks import collect_submodules

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

# pystray choisit son backend de tray a l'execution selon la plateforme
# (win32/darwin/xorg via Xlib) : meme raison que NOTIFY_HIDDEN ci-dessus,
# l'analyse statique de PyInstaller ne detecte pas ce choix conditionnel.
TRAY_HIDDEN = collect_submodules("pystray")

notifier_analysis = Analysis(
    ["notifier.py"],
    pathex=["."],
    hiddenimports=NOTIFY_HIDDEN + TRAY_HIDDEN,
    excludes=["tkinter", "PyInstaller", "pytest"],
    noarchive=False,
)

settings_analysis = Analysis(
    ["settings.py"],
    pathex=["."],
    excludes=["PyInstaller", "pytest"],
    noarchive=False,
)

MERGE(
    (notifier_analysis, "notifier", "watch2notif"),
    (settings_analysis, "settings", "watch2notif-settings"),
)

notifier_pyz = PYZ(notifier_analysis.pure)
notifier_exe = EXE(
    notifier_pyz,
    notifier_analysis.scripts,
    [],
    exclude_binaries=True,
    name="watch2notif",
    debug=False,
    strip=False,
    upx=False,
    # Pas de fenetre console : c'est un poller de fond, les notifications
    # desktop sont le seul retour visible attendu.
    console=False,
)

settings_pyz = PYZ(settings_analysis.pure)
settings_exe = EXE(
    settings_pyz,
    settings_analysis.scripts,
    [],
    exclude_binaries=True,
    name="watch2notif-settings",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

COLLECT(
    notifier_exe,
    notifier_analysis.binaries,
    notifier_analysis.zipfiles,
    notifier_analysis.datas,
    settings_exe,
    settings_analysis.binaries,
    settings_analysis.zipfiles,
    settings_analysis.datas,
    strip=False,
    upx=False,
    name="watch2notif",
)
