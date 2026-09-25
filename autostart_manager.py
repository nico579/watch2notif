"""Active/desactive le lancement automatique de notifier.py au demarrage
de la session, selon l'OS courant (Windows/Linux/Mac). Utilise par
settings.py via la case a cocher "demarrer avec le systeme".
"""
import os
import platform
import subprocess
import sys
from pathlib import Path


def frozen() -> bool:
    """Vrai lorsque le programme tourne depuis un bundle PyInstaller."""
    return bool(getattr(sys, "frozen", False))


# __file__ pointe vers le dossier d'extraction temporaire de PyInstaller
# une fois fige, pas vers le dossier de l'executable.
PROJECT_DIR = Path(sys.executable if frozen() else __file__).resolve().parent
NOTIFIER_PATH = PROJECT_DIR / "notifier.py"

LINUX_SERVICE_NAME = "watch2notif.service"
MAC_LABEL = "com.nico.watch2notif"


def _notifier_command() -> list:
    """Commande a lancer pour demarrer le poller de fond, adaptee selon
    qu'on tourne depuis les sources ou depuis le bundle fige : dans ce
    dernier cas, watch2notif.exe (executable unique, poller + panneau de
    reglage via --settings) se trouve a cote de l'executable courant."""
    if frozen():
        suffix = ".exe" if platform.system() == "Windows" else ""
        binary = Path(sys.executable).parent / f"watch2notif{suffix}"
        return [str(binary)]
    if platform.system() == "Windows":
        return [str(Path(sys.executable).with_name("pythonw.exe")), str(NOTIFIER_PATH)]
    return [sys.executable, str(NOTIFIER_PATH)]


def _windows_startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _windows_startup_file() -> Path:
    """Raccourci du dossier Demarrage, meme mecanisme que blink2video et
    lidar2map."""
    return _windows_startup_dir() / "watch2notif.lnk"


def _windows_legacy_file() -> Path:
    """Script .vbs des versions <= 0.2.3, remplace par le raccourci."""
    return _windows_startup_dir() / "watch2notif.vbs"


def _linux_service_file() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / LINUX_SERVICE_NAME


def _mac_plist_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def is_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
        return _windows_startup_file().exists() or _windows_legacy_file().exists()
    if system == "Linux":
        return _linux_service_file().exists()
    if system == "Darwin":
        return _mac_plist_file().exists()
    return False


def enable() -> None:
    system = platform.system()
    if system == "Windows":
        _enable_windows()
    elif system == "Linux":
        _enable_linux()
    elif system == "Darwin":
        _enable_mac()
    else:
        raise RuntimeError(f"OS non supporte pour l'autostart: {system}")


def disable() -> None:
    system = platform.system()
    if system == "Windows":
        _disable_windows()
    elif system == "Linux":
        _disable_linux()
    elif system == "Darwin":
        _disable_mac()
    else:
        raise RuntimeError(f"OS non supporte pour l'autostart: {system}")


def migrer_ancien_demarrage() -> bool:
    """Remplace le .vbs d'une version <= 0.2.3 par le raccourci, sans
    toucher au choix de l'utilisateur : rien si le demarrage automatique
    n'etait pas actif. Vrai si un remplacement a eu lieu."""
    if platform.system() != "Windows" or not _windows_legacy_file().exists():
        return False
    _enable_windows()
    return True


def _chaine_ps(valeur: str) -> str:
    """Chaine litterale PowerShell : seule l'apostrophe se double."""
    return "'" + valeur.replace("'", "''") + "'"


def _enable_windows() -> None:
    """Raccourci .lnk dans le dossier Demarrage, cree par l'interface COM de
    l'explorateur via PowerShell, present sur tout Windows. Aucune fenetre
    ne s'ouvre : l'executable est construit sans console (console=False),
    comme pythonw.exe depuis les sources.

    Remplace le script .vbs des versions <= 0.2.3 : VBScript est en cours de
    retrait de Windows, et wscript lisait ce script, ecrit en UTF-8 sans BOM,
    dans la page de code ANSI (un chemin accentue ne menait nulle part)."""
    commande = _notifier_command()
    cible = _windows_startup_file()
    cible.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({cible});"
        "$s.TargetPath = {executable}; $s.Arguments = {arguments};"
        "$s.WorkingDirectory = {dossier}; $s.WindowStyle = 7;"
        "$s.Description = 'watch2notif'; $s.Save()"
    ).format(
        cible=_chaine_ps(str(cible)),
        executable=_chaine_ps(commande[0]),
        arguments=_chaine_ps(subprocess.list2cmdline(commande[1:])),
        dossier=_chaine_ps(str(PROJECT_DIR)),
    )
    resultat = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace", check=False,
        # CREATE_NO_WINDOW seul : avec DETACHED_PROCESS, il serait ignore
        # (voir self_update.py, corrige en 0.1.9).
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if resultat.returncode != 0 or not cible.exists():
        raise RuntimeError("raccourci de demarrage non cree : "
                           + ((resultat.stderr or "").strip() or str(cible)))
    # Deux entrees lanceraient deux fois watch2notif a l'ouverture de session.
    _windows_legacy_file().unlink(missing_ok=True)


def _disable_windows() -> None:
    # Le .vbs d'une version <= 0.2.3 aussi : sinon il relancerait watch2notif.
    for path in (_windows_startup_file(), _windows_legacy_file()):
        path.unlink(missing_ok=True)


def _enable_linux() -> None:
    service_content = (
        "[Unit]\n"
        "Description=watch2notif (desktop notifications from RSS feeds and other sources)\n"
        "After=graphical-session.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={PROJECT_DIR}\n"
        f"ExecStart={' '.join(_notifier_command())}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    service_file = _linux_service_file()
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(service_content, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", LINUX_SERVICE_NAME], check=True)


def _disable_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", LINUX_SERVICE_NAME], check=False)
    path = _linux_service_file()
    if path.exists():
        path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def _enable_mac() -> None:
    plist_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"    <key>Label</key>\n    <string>{MAC_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n    <array>\n"
        + "".join(f"        <string>{part}</string>\n" for part in _notifier_command())
        + "    </array>\n"
        f"    <key>WorkingDirectory</key>\n    <string>{PROJECT_DIR}</string>\n"
        "    <key>RunAtLoad</key>\n    <true/>\n"
        # Relancer uniquement apres un crash. Avec KeepAlive=true, le choix
        # "Quitter" du tray et le helper de mise a jour etaient combattus par
        # launchd, qui redemarrait aussitot l'ancienne instance.
        "    <key>KeepAlive</key>\n"
        "    <dict>\n"
        "        <key>SuccessfulExit</key>\n"
        "        <false/>\n"
        "    </dict>\n"
        "</dict>\n</plist>\n"
    )
    plist_file = _mac_plist_file()
    plist_file.parent.mkdir(parents=True, exist_ok=True)
    plist_file.write_text(plist_content, encoding="utf-8")
    subprocess.run(["launchctl", "load", str(plist_file)], check=True)


def _disable_mac() -> None:
    plist_file = _mac_plist_file()
    if plist_file.exists():
        subprocess.run(["launchctl", "unload", str(plist_file)], check=False)
        plist_file.unlink()
