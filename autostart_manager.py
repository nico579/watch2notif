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


def _windows_startup_file() -> Path:
    appdata = os.environ["APPDATA"]
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "watch2notif.vbs"


def _linux_service_file() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / LINUX_SERVICE_NAME


def _mac_plist_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def is_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
        return _windows_startup_file().exists()
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


def _enable_windows() -> None:
    quoted = " ".join(f'""{part}""' for part in _notifier_command())
    vbs_content = (
        'Set shell = CreateObject("WScript.Shell")\n'
        f'shell.CurrentDirectory = "{PROJECT_DIR}"\n'
        f'shell.Run "{quoted}", 0, False\n'
    )
    _windows_startup_file().write_text(vbs_content, encoding="utf-8")


def _disable_windows() -> None:
    path = _windows_startup_file()
    if path.exists():
        path.unlink()


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
        "    <key>KeepAlive</key>\n    <true/>\n"
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
