"""Preparation et installation transactionnelle des mises a jour.

Le processus principal telecharge et valide entierement le nouveau bundle.
Un petit helper externe attend ensuite sa fermeture, remplace le dossier (ou
la .app macOS) d'un seul bloc, recopie uniquement les donnees utilisateur et
redemarre watch2notif. Le helper peut restaurer l'ancien bundle si le swap ou
le redemarrage echoue.
"""

from __future__ import annotations

import hashlib
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path


MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024
MAX_EXTRACTED_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 30_000
MAX_LINK_SIZE = 4096
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
PRESERVED_NAMES = ("config.json", "state", "watch2notif.log")


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


def _asset_url_is_allowed(url: str, expected_name: str, depot: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    expected_prefix = f"/{depot}/releases/download/"
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "github.com"
        and parsed.path.startswith(expected_prefix)
        and parsed.path.endswith("/" + urllib.parse.quote(expected_name))
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def select_asset(info: dict, layout: InstallLayout, depot: str) -> dict:
    assets = [asset for asset in info.get("assets", []) if asset.get("name") == layout.asset_name]
    if len(assets) != 1:
        raise UpdateError("missing_asset", layout.asset_name)

    asset = dict(assets[0])
    if asset.get("state") != "uploaded":
        raise UpdateError("invalid_asset", f"etat de l'asset: {asset.get('state')!r}")

    try:
        size = int(asset.get("size"))
    except (TypeError, ValueError):
        size = 0
    if not 0 < size <= MAX_ARCHIVE_SIZE:
        raise UpdateError("invalid_asset", f"taille invalide: {size}")

    digest = str(asset.get("digest") or "").lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise UpdateError("invalid_asset", "empreinte SHA-256 absente ou invalide")

    url = str(asset.get("browser_download_url") or "")
    if not _asset_url_is_allowed(url, layout.asset_name, depot):
        raise UpdateError("invalid_asset", "URL de telechargement inattendue")

    asset["size"] = size
    asset["digest"] = digest
    asset["browser_download_url"] = url
    return asset


def _redirect_url_is_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host in ALLOWED_DOWNLOAD_HOSTS or host.endswith(".githubusercontent.com")
    )


def download_asset(asset: dict, destination: Path, opener=urllib.request.urlopen) -> None:
    """Telecharge vers .part, puis publie seulement apres taille et SHA-256."""
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    received = 0
    stream_completed = False
    request = urllib.request.Request(
        asset["browser_download_url"],
        headers={"Accept": "application/octet-stream", "User-Agent": "watch2notif-updater"},
    )
    try:
        with opener(request, timeout=30) as response:
            final_url = getattr(response, "geturl", lambda: asset["browser_download_url"])()
            if not _redirect_url_is_allowed(final_url):
                raise UpdateError("invalid_asset", "redirection de telechargement inattendue")
            content_length = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
            if content_length is not None and int(content_length) != asset["size"]:
                raise UpdateError("integrity_failed", "taille HTTP differente de la release")

            with partial.open("xb") as output:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > asset["size"] or received > MAX_ARCHIVE_SIZE:
                        raise UpdateError("integrity_failed", "telechargement plus grand qu'annonce")
                    output.write(chunk)
                    digest.update(chunk)
                stream_completed = True
    except UpdateError:
        raise
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise UpdateError("download_failed", str(exc)) from exc
    finally:
        if partial.exists() and not stream_completed:
            partial.unlink(missing_ok=True)

    expected_digest = asset["digest"].split(":", 1)[1]
    if received != asset["size"]:
        partial.unlink(missing_ok=True)
        raise UpdateError("integrity_failed", f"{received} octets recus, {asset['size']} attendus")
    if digest.hexdigest() != expected_digest:
        partial.unlink(missing_ok=True)
        raise UpdateError("integrity_failed", "empreinte SHA-256 differente")
    os.replace(partial, destination)


def _member_parts(name: str) -> tuple[tuple[str, ...], bool]:
    if not isinstance(name, str) or not name or "\x00" in name or len(name) > 4096:
        raise UpdateError("unsafe_archive", "nom de membre invalide")
    normalized = name.replace("\\", "/")
    is_directory = normalized.endswith("/")
    if is_directory:
        normalized = normalized[:-1]
    if not normalized or normalized.startswith("/") or normalized.startswith("//"):
        raise UpdateError("unsafe_archive", name)
    if re.match(r"^[A-Za-z]:", normalized):
        raise UpdateError("unsafe_archive", name)
    parts = tuple(normalized.split("/"))
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        raise UpdateError("unsafe_archive", name)
    return parts, is_directory


def _validate_member_set(entries: list[tuple[str, tuple[str, ...]]], expected_root: str) -> None:
    if len(entries) > MAX_ARCHIVE_MEMBERS:
        raise UpdateError("unsafe_archive", "archive trop volumineuse")
    seen: set[str] = set()
    for name, parts in entries:
        if not parts or parts[0] != expected_root:
            raise UpdateError("unsafe_archive", f"racine inattendue: {name}")
        folded = "/".join(parts).casefold()
        if folded in seen:
            raise UpdateError("unsafe_archive", f"membre duplique: {name}")
        seen.add(folded)


def _ensure_no_symlink_parent(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise UpdateError("unsafe_archive", f"ecriture sous un lien: {'/'.join(parts)}")
    return root.joinpath(*parts)


def _validate_symlink_target(member_parts: tuple[str, ...], target: str, expected_root: str) -> None:
    if not target or "\x00" in target or "\\" in target or target.startswith("/"):
        raise UpdateError("unsafe_archive", f"lien invalide: {target!r}")
    if re.match(r"^[A-Za-z]:", target):
        raise UpdateError("unsafe_archive", f"lien invalide: {target!r}")
    resolved = list(member_parts[:-1])
    for part in target.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if len(resolved) <= 1:
                raise UpdateError("unsafe_archive", f"lien sortant: {target!r}")
            resolved.pop()
        else:
            if ":" in part:
                raise UpdateError("unsafe_archive", f"lien invalide: {target!r}")
            resolved.append(part)
    if not resolved or resolved[0] != expected_root:
        raise UpdateError("unsafe_archive", f"lien sortant: {target!r}")


def _copy_limited(source, destination, expected_size: int) -> None:
    copied = 0
    while True:
        chunk = source.read(DOWNLOAD_CHUNK_SIZE)
        if not chunk:
            break
        copied += len(chunk)
        if copied > expected_size:
            raise UpdateError("unsafe_archive", "membre plus grand qu'annonce")
        destination.write(chunk)
    if copied != expected_size:
        raise UpdateError("unsafe_archive", "membre tronque")


def _extract_zip(archive: Path, destination: Path, expected_root: str) -> None:
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            entries = [(info.filename, _member_parts(info.filename)[0]) for info in infos]
            _validate_member_set(entries, expected_root)
            total = sum(info.file_size for info in infos)
            if total > MAX_EXTRACTED_SIZE:
                raise UpdateError("unsafe_archive", "contenu decompresse trop volumineux")

            for info in infos:
                parts, name_says_directory = _member_parts(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                is_link = file_type == stat.S_IFLNK
                is_directory = name_says_directory or info.is_dir() or file_type == stat.S_IFDIR
                if info.flag_bits & 0x1:
                    raise UpdateError("unsafe_archive", "archive chiffree")
                if file_type not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}:
                    raise UpdateError("unsafe_archive", f"type de membre interdit: {info.filename}")
                destination_path = _ensure_no_symlink_parent(destination, parts)

                if is_directory:
                    destination_path.mkdir(parents=True, exist_ok=True)
                    continue
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                if is_link:
                    if info.file_size > MAX_LINK_SIZE or os.name == "nt":
                        raise UpdateError("unsafe_archive", f"lien non supporte: {info.filename}")
                    target = zipped.read(info).decode("utf-8")
                    _validate_symlink_target(parts, target, expected_root)
                    os.symlink(target, destination_path)
                    continue

                with zipped.open(info) as source, destination_path.open("xb") as output:
                    _copy_limited(source, output, info.file_size)
                if os.name != "nt" and mode:
                    destination_path.chmod(mode & 0o777)
    except UpdateError:
        raise
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise UpdateError("unsafe_archive", str(exc)) from exc


def _extract_tar(archive: Path, destination: Path, expected_root: str) -> None:
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            entries = [(member.name, _member_parts(member.name)[0]) for member in members]
            _validate_member_set(entries, expected_root)
            total = sum(member.size for member in members if member.isfile())
            if total > MAX_EXTRACTED_SIZE:
                raise UpdateError("unsafe_archive", "contenu decompresse trop volumineux")

            hardlinks = []
            for member in members:
                parts, _ = _member_parts(member.name)
                destination_path = _ensure_no_symlink_parent(destination, parts)
                if member.isdir():
                    destination_path.mkdir(parents=True, exist_ok=True)
                    if os.name != "nt":
                        destination_path.chmod(member.mode & 0o777)
                elif member.isfile():
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise UpdateError("unsafe_archive", f"membre illisible: {member.name}")
                    with source, destination_path.open("xb") as output:
                        _copy_limited(source, output, member.size)
                    if os.name != "nt":
                        destination_path.chmod(member.mode & 0o777)
                elif member.issym():
                    if os.name == "nt":
                        raise UpdateError("unsafe_archive", f"lien non supporte: {member.name}")
                    _validate_symlink_target(parts, member.linkname, expected_root)
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(member.linkname, destination_path)
                elif member.islnk():
                    hardlinks.append((member, parts, destination_path))
                else:
                    raise UpdateError("unsafe_archive", f"type de membre interdit: {member.name}")

            for member, parts, destination_path in hardlinks:
                target_parts, _ = _member_parts(member.linkname)
                if target_parts[0] != expected_root:
                    raise UpdateError("unsafe_archive", f"hardlink sortant: {member.linkname}")
                target_path = _ensure_no_symlink_parent(destination, target_parts)
                if not target_path.is_file() or target_path.is_symlink():
                    raise UpdateError("unsafe_archive", f"cible de hardlink invalide: {member.linkname}")
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                os.link(target_path, destination_path)
    except UpdateError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise UpdateError("unsafe_archive", str(exc)) from exc


def extract_archive(archive: Path, destination: Path, layout: InstallLayout) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    if layout.archive_kind == "zip":
        _extract_zip(archive, destination, layout.expected_root)
    elif layout.archive_kind == "tar":
        _extract_tar(archive, destination, layout.expected_root)
    else:
        raise UpdateError("unsafe_archive", f"format inconnu: {layout.archive_kind}")

    children = list(destination.iterdir())
    payload = destination / layout.expected_root
    if len(children) != 1 or children[0].name != layout.expected_root or not payload.is_dir() or payload.is_symlink():
        raise UpdateError("unsafe_archive", "racine du bundle invalide")
    return payload


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

New-Item -ItemType File -Force -Path $ReadyFile | Out-Null
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

: > "$ready_file" || exit 10
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
    """Lance le helper, verifie qu'il est pret, puis rend la main a Qt."""
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
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
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

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if ready_file.exists():
                return
            if process is not None and process.poll() is not None:
                break
            time.sleep(0.1)
        raise UpdateError("helper_failed", "le helper n'a pas confirme son demarrage")
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError("helper_failed", str(exc)) from exc


def commit_prepared_update(prepared: PreparedUpdate) -> None:
    """Autorise le helper deja pret a commencer une fois Qt en train de quitter."""
    _validated_transaction_paths(prepared)
    ready_file = prepared.staging_root / "helper.ready"
    if not ready_file.is_file():
        raise UpdateError("helper_failed", "le helper n'est plus pret")
    try:
        go_file = prepared.staging_root / "helper.go"
        go_file.touch(exist_ok=False)
    except OSError as exc:
        raise UpdateError("helper_failed", str(exc)) from exc
    deadline = time.monotonic() + 8
    acknowledgement = Path(str(go_file) + ".ack")
    while time.monotonic() < deadline:
        if acknowledgement.is_file():
            return
        time.sleep(0.05)
    abort_prepared_update(prepared)
    raise UpdateError("helper_failed", "le helper n'a pas confirme la transaction")


def abort_prepared_update(prepared: PreparedUpdate) -> None:
    """Demande a un helper en attente de renoncer et de nettoyer son staging."""
    try:
        (prepared.staging_root / "helper.abort").touch(exist_ok=True)
    except OSError:
        pass
