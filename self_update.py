"""Preparation et installation transactionnelle des mises a jour.

Le processus principal telecharge et valide entierement le nouveau bundle.
Un petit helper externe attend ensuite sa fermeture, remplace le dossier (ou
la .app macOS) d'un seul bloc, recopie uniquement les donnees utilisateur et
redemarre watch2notif. Le helper peut restaurer l'ancien bundle si le swap ou
le redemarrage echoue.
"""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from nico579_commons import maj_archive


MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 30_000
PRESERVED_NAMES = ("config.json", "state", "watch2notif.log", "notification_history.json")


class UpdateError(RuntimeError):
    """Erreur exploitable par l'interface pour afficher un message traduit."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def payload(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class InstallLayout:
    system: str
    machine: str
    asset_name: str
    archive_kind: str
    expected_root: str
    install_root: Path
    data_relative: Path
    executable_relative: Path


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    token: str
    layout: InstallLayout
    staging_root: Path
    payload_root: Path
    backup_root: Path
    failed_root: Path


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


def _mac_app_root(executable: Path) -> Path:
    for candidate in (executable, *executable.parents):
        if candidate.suffix.lower() == ".app":
            try:
                relative = executable.relative_to(candidate)
            except ValueError:
                continue
            if len(relative.parts) >= 3 and relative.parts[:2] == ("Contents", "MacOS"):
                return candidate
    raise UpdateError("unsafe_install", f"application .app introuvable depuis {executable}")


def install_layout(
    executable: Path | None = None,
    system: str | None = None,
    machine: str | None = None,
    frozen: bool | None = None,
) -> InstallLayout:
    """Decrit le bundle courant et le payload exact qui peut le remplacer."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if executable is None and not frozen:
        raise UpdateError("source_mode")

    executable = Path(executable or sys.executable).resolve()
    system = system or platform.system()
    machine = machine or platform.machine()
    asset_name, archive_kind, expected_root = target_for(system, machine)

    if system == "Darwin":
        install_root = _mac_app_root(executable)
        data_relative = Path("Contents") / "MacOS"
        executable_relative = data_relative / "watch2notif"
    else:
        install_root = executable.parent
        data_relative = Path(".")
        executable_relative = Path("watch2notif.exe" if system == "Windows" else "watch2notif")

    install_root = install_root.resolve()
    filesystem_root = Path(install_root.anchor).resolve()
    try:
        user_home = Path.home().resolve()
    except OSError:
        user_home = None
    if install_root == filesystem_root or (user_home is not None and install_root == user_home):
        raise UpdateError("unsafe_install", str(install_root))

    if system != "Darwin":
        # Le produit publie un dossier onedir nomme watch2notif. Remplacer le
        # parent de l'executable serait destructeur si quelqu'un avait copie
        # exe + _internal directement sur son Bureau ou dans Downloads.
        if install_root.name.casefold() != "watch2notif":
            raise UpdateError("unsafe_install", f"dossier non dedie: {install_root}")
        allowed_names = {
            executable_relative.name,
            "_internal",
            ".watch2notif.lock",
            *PRESERVED_NAMES,
        }
        try:
            unexpected = sorted(path.name for path in install_root.iterdir() if path.name not in allowed_names)
        except OSError as exc:
            raise UpdateError("unsafe_install", str(exc)) from exc
        if unexpected:
            raise UpdateError("unsafe_install", f"contenu inconnu: {', '.join(unexpected[:5])}")
        if not (install_root / "_internal").is_dir():
            raise UpdateError("unsafe_install", "dossier _internal courant absent")

    expected_executable = install_root / executable_relative
    if executable != expected_executable.resolve():
        raise UpdateError("unsafe_install", f"executable inattendu: {executable}")

    return InstallLayout(
        system=system,
        machine=machine,
        asset_name=asset_name,
        archive_kind=archive_kind,
        expected_root=expected_root,
        install_root=install_root,
        data_relative=data_relative,
        executable_relative=executable_relative,
    )


def can_install_automatically() -> tuple[bool, str]:
    if not getattr(sys, "frozen", False):
        return False, "source_mode"
    try:
        install_layout()
    except UpdateError as exc:
        return False, exc.code
    return True, ""


def _en_update_error(erreur) -> "UpdateError":
    """Un refus de nico579_commons.maj_archive devient l'UpdateError que
    l'interface sait afficher : le même code grossier qu'avant (invalid_asset,
    integrity_failed, download_failed, unsafe_archive), le détail en clair."""
    code = "missing_asset" if erreur.code == "asset_absent" else erreur.categorie
    return UpdateError(code, erreur.message("fr"))


def select_asset(info: dict, layout: InstallLayout, depot: str) -> dict:
    """L'unique fichier de release de ce nom, finalisé, avec taille, empreinte
    SHA-256 et URL du dépôt officiel (nico579_commons.maj_archive)."""
    try:
        return maj_archive.choisir_asset(
            info.get("assets"), layout.asset_name, depot, taille_max=MAX_ARCHIVE_SIZE)
    except maj_archive.ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def download_asset(asset: dict, destination: Path, opener=urllib.request.urlopen) -> None:
    """Telecharge vers .part, puis publie seulement apres taille et SHA-256."""
    # Le dépôt est celui de l'URL, déjà liée au dépôt attendu par select_asset().
    morceaux = urllib.parse.urlparse(asset["browser_download_url"]).path.split("/")
    try:
        maj_archive.telecharger(
            asset["browser_download_url"], destination, asset["size"], asset["digest"],
            depot="/".join(morceaux[1:3]), agent="watch2notif-updater",
            nom=asset["name"], ouvrir=opener, taille_max=MAX_ARCHIVE_SIZE, delai_s=30)
    except maj_archive.ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def extract_archive(archive: Path, destination: Path, layout: InstallLayout) -> Path:
    """Déballe l'archive sans rien écrire hors de `destination` et rend le
    dossier du bundle (nico579_commons.maj_archive)."""
    try:
        return maj_archive.extraire(
            archive, destination, racine=layout.expected_root,
            taille_max=MAX_EXTRACTED_SIZE, membres_max=MAX_ARCHIVE_MEMBERS)
    except maj_archive.ErreurMiseAJour as erreur:
        raise _en_update_error(erreur) from erreur


def _validate_payload(payload: Path, layout: InstallLayout) -> Path:
    executable = payload / layout.executable_relative
    if not executable.is_file() or executable.is_symlink():
        raise UpdateError("invalid_payload", f"executable absent: {layout.executable_relative}")
    data_dir = payload / layout.data_relative
    for name in PRESERVED_NAMES:
        if (data_dir / name).exists() or (data_dir / name).is_symlink():
            raise UpdateError("invalid_payload", f"donnee mutable presente dans le bundle: {name}")
    if layout.system in {"Windows", "Linux"} and not (payload / "_internal").is_dir():
        raise UpdateError("invalid_payload", "dossier _internal absent")
    if layout.system != "Windows" and not os.access(executable, os.X_OK):
        raise UpdateError("invalid_payload", "executable non executable")
    return executable


def _smoke_test(executable: Path, version: str, system: str) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if system == "Windows" else 0
    try:
        result = subprocess.run(
            [str(executable), "--self-test-version", version],
            cwd=executable.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("invalid_payload", f"auto-test impossible: {exc}") from exc
    if result.returncode != 0:
        raise UpdateError("invalid_payload", f"auto-test echoue (code {result.returncode})")


def prepare_update(
    info: dict,
    depot: str,
    layout: InstallLayout | None = None,
    opener=urllib.request.urlopen,
    smoke_test: bool = True,
) -> PreparedUpdate:
    """Telecharge, verifie et extrait le bundle sans toucher a l'installation."""
    layout = layout or install_layout()
    asset = select_asset(info, layout, depot)
    version = str(info.get("version") or "")
    if not version:
        raise UpdateError("invalid_asset", "version absente")

    token = uuid.uuid4().hex
    staging_root = None
    try:
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{layout.install_root.name}.update-", dir=layout.install_root.parent)
        ).resolve()
        archive_suffix = ".tar.gz" if layout.archive_kind == "tar" else ".zip"
        archive = staging_root / f"download{archive_suffix}"
        download_asset(asset, archive, opener=opener)
        payload = extract_archive(archive, staging_root / "extracted", layout)
        executable = _validate_payload(payload, layout)
        if smoke_test:
            _smoke_test(executable, version, layout.system)

        backup_root = layout.install_root.parent / f".{layout.install_root.name}.backup-{token}"
        failed_root = layout.install_root.parent / f".{layout.install_root.name}.failed-{token}"
        if backup_root.exists() or failed_root.exists():
            raise UpdateError("unsafe_install", "chemin de transaction deja present")
        return PreparedUpdate(
            version=version,
            token=token,
            layout=layout,
            staging_root=staging_root,
            payload_root=payload,
            backup_root=backup_root,
            failed_root=failed_root,
        )
    except UpdateError:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)
        raise
    except OSError as exc:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)
        raise UpdateError("prepare_failed", str(exc)) from exc


def cleanup_prepared(prepared: PreparedUpdate) -> None:
    staging = prepared.staging_root.resolve()
    expected_parent = prepared.layout.install_root.parent.resolve()
    if staging.parent == expected_parent and staging.name.startswith(f".{prepared.layout.install_root.name}.update-"):
        shutil.rmtree(staging, ignore_errors=True)


_WINDOWS_HELPER = r'''param(
    [int]$ParentPid,
    [string]$Current,
    [string]$Payload,
    [string]$Staging,
    [string]$Backup,
    [string]$Failed,
    [string]$DataRelative,
    [string]$ExecutableRelative,
    [string]$ReadyFile,
    [string]$GoFile,
    [string]$LogFile
)
$ErrorActionPreference = "Stop"
function Write-UpdateLog([string]$Message) {
    try { Add-Content -LiteralPath $LogFile -Value ((Get-Date -Format o) + " " + $Message) -Encoding UTF8 } catch {}
}
function Start-Watch2notif([string]$Root) {
    $exe = Join-Path $Root $ExecutableRelative
    return Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -WindowStyle Hidden -PassThru
}
function Copy-UserData([string]$OldRoot, [string]$NewRoot) {
    $oldData = Join-Path $OldRoot $DataRelative
    $newData = Join-Path $NewRoot $DataRelative
    New-Item -ItemType Directory -Force -Path $newData | Out-Null
    foreach ($name in @("config.json", "watch2notif.log")) {
        $source = Join-Path $oldData $name
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $newData $name) -Force
        }
    }
    $oldState = Join-Path $oldData "state"
    $newState = Join-Path $newData "state"
    if (Test-Path -LiteralPath $oldState -PathType Container) {
        if (Test-Path -LiteralPath $newState) { throw "candidate unexpectedly contains state" }
        Copy-Item -LiteralPath $oldState -Destination $newState -Recurse -Force
    }
}
function Restore-OldVersion {
    try {
        if (Test-Path -LiteralPath $Current) {
            if (Test-Path -LiteralPath $Failed) { throw "failed destination already exists" }
            Move-Item -LiteralPath $Current -Destination $Failed
        }
        if (Test-Path -LiteralPath $Backup) {
            if (Test-Path -LiteralPath $Current) { throw "current path still exists during rollback" }
            Move-Item -LiteralPath $Backup -Destination $Current
            Start-Watch2notif $Current | Out-Null
        }
    } catch { Write-UpdateLog ("rollback failed: " + $_.Exception.Message) }
}

Write-UpdateLog ("helper started (pid " + $PID + ")")
New-Item -ItemType File -Force -Path $ReadyFile | Out-Null
Write-UpdateLog "ready file written, waiting for go"
$readyDeadline = (Get-Date).AddSeconds(60)
while (-not (Test-Path -LiteralPath $GoFile)) {
    if (Test-Path -LiteralPath (Join-Path $Staging "helper.abort")) {
        Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
        exit 8
    }
    if ((Get-Date) -gt $readyDeadline) { Write-UpdateLog "update was not committed"; exit 9 }
    Start-Sleep -Milliseconds 100
}
if (Test-Path -LiteralPath (Join-Path $Staging "helper.abort")) {
    Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    exit 8
}
New-Item -ItemType File -Force -Path ($GoFile + ".ack") | Out-Null
Write-UpdateLog "go received, ack written, waiting for parent to exit"
Start-Sleep -Milliseconds 500
try {
    $parentDeadline = (Get-Date).AddMinutes(5)
    while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        if ((Get-Date) -gt $parentDeadline) { Write-UpdateLog "parent did not exit"; exit 10 }
        Start-Sleep -Milliseconds 250
    }
    if ((Test-Path -LiteralPath $Backup) -or (Test-Path -LiteralPath $Failed)) {
        Write-UpdateLog "transaction destination appeared unexpectedly"
        Start-Watch2notif $Current | Out-Null
        exit 11
    }
    Write-UpdateLog "parent exited, starting swap"
    Move-Item -LiteralPath $Current -Destination $Backup
    try {
        Move-Item -LiteralPath $Payload -Destination $Current
        Copy-UserData $Backup $Current
    } catch {
        Write-UpdateLog ("swap failed: " + $_.Exception.Message)
        Restore-OldVersion
        exit 2
    }

    try {
        $newProcess = Start-Watch2notif $Current
        Start-Sleep -Seconds 5
        if ($newProcess.HasExited) { throw "new process exited too early" }
    } catch {
        Write-UpdateLog ("restart failed: " + $_.Exception.Message)
        Restore-OldVersion
        exit 3
    }

    Write-UpdateLog "update succeeded, new version running"
    Remove-Item -LiteralPath $Backup -Recurse -Force
    Remove-Item -LiteralPath $Staging -Recurse -Force
    exit 0
} catch {
    Write-UpdateLog ("update failed: " + $_.Exception.Message)
    if ((-not (Test-Path -LiteralPath $Current)) -and (Test-Path -LiteralPath $Backup)) {
        try { Move-Item -LiteralPath $Backup -Destination $Current; Start-Watch2notif $Current | Out-Null } catch {}
    } elseif ((Test-Path -LiteralPath $Current) -and (-not (Test-Path -LiteralPath $Backup))) {
        try { Start-Watch2notif $Current | Out-Null } catch {}
    }
    exit 1
}
'''


_POSIX_HELPER = r'''#!/bin/sh
parent_pid=$1
current=$2
payload=$3
staging=$4
backup=$5
failed=$6
data_relative=$7
executable_relative=$8
system_name=$9
ready_file=${10}
go_file=${11}
log_file=${12}
service_file=${13}
mac_plist=${14}

write_log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$log_file" 2>/dev/null || true
}
copy_user_data() {
    old_data=$backup/$data_relative
    new_data=$current/$data_relative
    mkdir -p "$new_data" || return 1
    for name in config.json watch2notif.log; do
        if [ -f "$old_data/$name" ]; then
            cp -p "$old_data/$name" "$new_data/$name" || return 1
        fi
    done
    if [ -d "$old_data/state" ]; then
        [ ! -e "$new_data/state" ] || return 1
        cp -R -p "$old_data/state" "$new_data/state" || return 1
    fi
}
start_version() {
    root=$1
    exe=$root/$executable_relative
    if [ "$system_name" = "Darwin" ] && [ -f "$mac_plist" ]; then
        launchctl load "$mac_plist" >/dev/null 2>&1 || return 1
        sleep 5
        launchctl list com.nico.watch2notif 2>/dev/null | /usr/bin/grep -Eq '"PID"[[:space:]]*=[[:space:]]*[0-9]+'
        return $?
    fi
    if [ "$system_name" = "Linux" ] && [ -f "$service_file" ]; then
        transition_waited=0
        while :; do
            service_state=$(systemctl --user show watch2notif.service --property=ActiveState --value 2>/dev/null || true)
            [ "$service_state" != "activating" ] && [ "$service_state" != "deactivating" ] && break
            sleep 1
            transition_waited=$((transition_waited + 1))
            [ "$transition_waited" -lt 30 ] || return 1
        done
        systemctl --user reset-failed watch2notif.service >/dev/null 2>&1 || true
        systemctl --user start watch2notif.service >/dev/null 2>&1 || return 1
        sleep 5
        systemctl --user is-active --quiet watch2notif.service
        return $?
    fi
    working_dir=$(dirname "$exe")
    (cd "$working_dir" && exec "$exe" >/dev/null 2>&1) &
    new_pid=$!
    sleep 5
    kill -0 "$new_pid" 2>/dev/null
}
restore_old() {
    if [ "$system_name" = "Darwin" ] && [ -f "$mac_plist" ]; then
        launchctl unload "$mac_plist" >/dev/null 2>&1 || true
    fi
    if [ "$system_name" = "Linux" ] && [ -f "$service_file" ]; then
        systemctl --user stop watch2notif.service >/dev/null 2>&1 || true
    fi
    if [ -e "$current" ]; then
        [ ! -e "$failed" ] || return 1
        mv "$current" "$failed" 2>/dev/null || return 1
    fi
    if [ -e "$backup" ]; then
        [ ! -e "$current" ] || return 1
        mv "$backup" "$current" 2>/dev/null || return 1
        start_version "$current" || true
    fi
}

write_log "helper started (pid $$)"
: > "$ready_file" || exit 10
write_log "ready file written, waiting for go"
waited=0
while [ ! -e "$go_file" ]; do
    if [ -e "$staging/helper.abort" ]; then
        rm -rf "$staging"
        exit 8
    fi
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -ge 60 ]; then
        write_log "update was not committed"
        exit 9
    fi
done
if [ -e "$staging/helper.abort" ]; then
    rm -rf "$staging"
    exit 8
fi
mac_unloaded=0
if [ "$system_name" = "Darwin" ] && [ -f "$mac_plist" ]; then
    if launchctl list com.nico.watch2notif >/dev/null 2>&1; then
        if launchctl unload "$mac_plist" >/dev/null 2>&1; then
            mac_unloaded=1
        else
            write_log "could not unload LaunchAgent"
            exit 10
        fi
    fi
fi
: > "$go_file.ack" || exit 10
write_log "go received, ack written, waiting for parent to exit"
sleep 1

waited=0
while kill -0 "$parent_pid" 2>/dev/null; do
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -ge 300 ]; then
        write_log "parent did not exit"
        if [ "$mac_unloaded" -eq 1 ]; then launchctl load "$mac_plist" >/dev/null 2>&1 || true; fi
        exit 11
    fi
done

if [ -e "$backup" ] || [ -L "$backup" ] || [ -e "$failed" ] || [ -L "$failed" ]; then
    write_log "transaction destination appeared unexpectedly"
    start_version "$current" || true
    exit 12
fi

write_log "parent exited, starting swap"
if ! mv "$current" "$backup"; then
    write_log "could not move current installation"
    start_version "$current" || true
    exit 12
fi
if ! mv "$payload" "$current"; then
    write_log "could not install candidate"
    restore_old
    exit 13
fi
if ! copy_user_data; then
    write_log "could not preserve user data"
    restore_old
    exit 14
fi
if ! start_version "$current"; then
    write_log "new version did not stay running"
    restore_old
    exit 15
fi

write_log "update succeeded, new version running"
rm -rf "$backup"
rm -rf "$staging"
exit 0
'''


def _validated_transaction_paths(prepared: PreparedUpdate) -> None:
    current = prepared.layout.install_root.resolve()
    parent = current.parent
    staging = prepared.staging_root.resolve()
    payload = prepared.payload_root.resolve()
    backup = prepared.backup_root.resolve()
    failed = prepared.failed_root.resolve()

    if not current.is_dir() or current == Path(current.anchor).resolve():
        raise UpdateError("unsafe_install", str(current))
    if staging.parent != parent or not staging.name.startswith(f".{current.name}.update-"):
        raise UpdateError("unsafe_install", str(staging))
    if staging not in payload.parents or not payload.is_dir():
        raise UpdateError("unsafe_install", str(payload))
    if backup.parent != parent or failed.parent != parent:
        raise UpdateError("unsafe_install", "backup hors du dossier attendu")
    if backup.exists() or failed.exists():
        raise UpdateError("unsafe_install", "backup deja present")


def _write_helper(contents: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="watch2notif-updater-", suffix=suffix)
    helper = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
        if os.name != "nt":
            helper.chmod(0o700)
    except Exception:
        helper.unlink(missing_ok=True)
        raise
    return helper


def _prepare_mac_launch_agent(plist: Path) -> None:
    """Empeche launchd de relancer l'ancien bundle pendant le swap.

    Le job charge garde son ancienne definition jusqu'au `unload` du helper ;
    le `load` qui suit le remplacement prendra cette definition corrigee.
    """
    if not plist.is_file():
        return
    try:
        data = plistlib.loads(plist.read_bytes())
        if data.get("Label") != "com.nico.watch2notif":
            raise UpdateError("helper_failed", "LaunchAgent watch2notif invalide")
        data["KeepAlive"] = {"SuccessfulExit": False}
        temporary = plist.with_suffix(plist.suffix + ".update.tmp")
        temporary.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML, sort_keys=False))
        os.replace(temporary, plist)
    except UpdateError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise UpdateError("helper_failed", f"LaunchAgent: {exc}") from exc


def launch_prepared_update(prepared: PreparedUpdate) -> None:
    """Lance le helper, verifie qu'il est pret, puis rend la main a l'appelant."""
    _validated_transaction_paths(prepared)
    layout = prepared.layout
    ready_file = prepared.staging_root / "helper.ready"
    go_file = prepared.staging_root / "helper.go"
    log_file = prepared.staging_root / "update-helper.log"
    service_file = Path.home() / ".config" / "systemd" / "user" / "watch2notif.service"
    mac_plist = Path.home() / "Library" / "LaunchAgents" / "com.nico.watch2notif.plist"
    if layout.system == "Darwin":
        _prepare_mac_launch_agent(mac_plist)

    common_args = [
        str(os.getpid()),
        str(layout.install_root),
        str(prepared.payload_root),
        str(prepared.staging_root),
        str(prepared.backup_root),
        str(prepared.failed_root),
        str(layout.data_relative),
        str(layout.executable_relative),
    ]

    try:
        if layout.system == "Windows":
            helper = _write_helper(_WINDOWS_HELPER, ".ps1")
            command = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(helper),
                "-ParentPid",
                common_args[0],
                "-Current",
                common_args[1],
                "-Payload",
                common_args[2],
                "-Staging",
                common_args[3],
                "-Backup",
                common_args[4],
                "-Failed",
                common_args[5],
                "-DataRelative",
                common_args[6],
                "-ExecutableRelative",
                common_args[7],
                "-ReadyFile",
                str(ready_file),
                "-GoFile",
                str(go_file),
                "-LogFile",
                str(log_file),
            ]
            # CREATE_NO_WINDOW seul : une console est bien creee, juste
            # invisible, contrairement a DETACHED_PROCESS (aucune console du
            # tout) qui rendait ce lancement de PowerShell erratique - parfois
            # 15s a demarrer, parfois un retour immediat (code 0) sans que le
            # script n'ait rien execute. Constate en reel (2026-09-07),
            # confirme par comparaison avec runtime.py de blink2video (meme
            # besoin, memes drapeaux disponibles) qui n'utilise que
            # CREATE_NO_WINDOW et n'a jamais eu ce symptome.
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=tempfile.gettempdir(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
        else:
            helper = _write_helper(_POSIX_HELPER, ".sh")
            command = [
                "/bin/sh",
                str(helper),
                *common_args,
                layout.system,
                str(ready_file),
                str(go_file),
                str(log_file),
                str(service_file),
                str(mac_plist),
            ]
            if layout.system == "Linux" and os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
                unit = f"watch2notif-update-{prepared.token[:12]}"
                result = subprocess.run(
                    ["systemd-run", "--user", "--collect", f"--unit={unit}", *command],
                    cwd=tempfile.gettempdir(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
                if result.returncode != 0:
                    raise UpdateError("helper_failed", f"systemd-run: {result.returncode}")
                process = None
            else:
                process = subprocess.Popen(
                    command,
                    cwd=tempfile.gettempdir(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )

        # 25s, pas 8 : sur Windows, le premier lancement d'un script PowerShell
        # inedit (nouveau fichier temporaire a chaque mise a jour) declenche un
        # scan AMSI/Defender qui peut a lui seul depasser 8s avant que le
        # helper n'atteigne sa premiere ligne. Constate en reel (2026-09-07,
        # session Claude) : le helper ecrit bien helper.ready et la mise a
        # jour aurait reussi, mais uniquement mesure avec une marge de 15s -
        # echouait systematiquement a 8s alors que le helper n'avait rien de
        # casse.
        wait_start = time.monotonic()
        deadline = wait_start + 25
        while time.monotonic() < deadline:
            if ready_file.exists():
                print(f"[maj] helper pret apres {time.monotonic() - wait_start:.1f}s")
                return
            if process is not None and process.poll() is not None:
                print(
                    f"[maj] le processus helper s'est termine (code {process.returncode}) "
                    f"apres {time.monotonic() - wait_start:.1f}s sans ecrire helper.ready"
                )
                break
            time.sleep(0.1)
        print(f"[maj] pas de confirmation du helper apres {time.monotonic() - wait_start:.1f}s")
        raise UpdateError("helper_failed", "le helper n'a pas confirme son demarrage")
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError("helper_failed", str(exc)) from exc


def commit_prepared_update(prepared: PreparedUpdate) -> None:
    """Autorise le helper deja pret a commencer une fois ce process en train de quitter."""
    _validated_transaction_paths(prepared)
    ready_file = prepared.staging_root / "helper.ready"
    if not ready_file.is_file():
        raise UpdateError("helper_failed", "le helper n'est plus pret")
    try:
        go_file = prepared.staging_root / "helper.go"
        go_file.touch(exist_ok=False)
    except OSError as exc:
        raise UpdateError("helper_failed", str(exc)) from exc
    wait_start = time.monotonic()
    deadline = wait_start + 8
    acknowledgement = Path(str(go_file) + ".ack")
    while time.monotonic() < deadline:
        if acknowledgement.is_file():
            print(f"[maj] transaction confirmee par le helper apres {time.monotonic() - wait_start:.1f}s")
            return
        time.sleep(0.05)
    print(f"[maj] pas d'accuse de reception du helper apres {time.monotonic() - wait_start:.1f}s")
    abort_prepared_update(prepared)
    raise UpdateError("helper_failed", "le helper n'a pas confirme la transaction")


def abort_prepared_update(prepared: PreparedUpdate) -> None:
    """Demande a un helper en attente de renoncer et de nettoyer son staging."""
    try:
        (prepared.staging_root / "helper.abort").touch(exist_ok=True)
    except OSError:
        pass
