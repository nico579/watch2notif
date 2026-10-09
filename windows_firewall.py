"""Read-only Windows firewall diagnosis and an explicitly requested LAN allow rule.

Importing this module and calling status never change the firewall. Only allow,
called by the user's button, requests Windows UAC. The persistent rule applies
to this packaged executable, TCP, one LAN IPv4 and local-subnet peers. The
pairing server still controls its own two-minute lifetime and one-use access.
"""
import base64
import ctypes
import gzip
import hashlib
import ipaddress
import json
import ntpath
import os
import re
import subprocess
import sys

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
CREATE_NO_WINDOW = 0x08000000
ELEVATION_ERRORS = {
    10: "policy_changed", 11: "rules_read_failed", 12: "rule_conflict",
    13: "rule_create_failed", 14: "block_disable_failed", 15: "verification_failed",
    16: "rollback_failed",
}


class _ShellExecuteInfo(ctypes.Structure):
    # Fixed-width Win32 integers also keep mocked CI calls portable.
    _fields_ = [("cbSize", ctypes.c_uint32), ("fMask", ctypes.c_uint32),
                ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int32),
                ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_uint32), ("hIcon", ctypes.c_void_p),
                ("hProcess", ctypes.c_void_p)]


def _winapi():
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = ctypes.c_int32
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int32
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    return shell, kernel, ole


def _last_error():
    return ctypes.get_last_error()


def _native_error():
    error = OSError("Windows elevation failed")
    error.winerror = _last_error()
    return error


def _elevate(script, timeout):
    """Ask Windows directly for UAC; wait on this process, without a parent console.

    Only a firewall script crosses the process boundary. There is no temporary
    script/result file, inherited output pipe, QR, API key or configuration.
    """
    shell, kernel, ole = _winapi()
    initialized = ole.CoInitializeEx(None, 6)  # Apartment-threaded, disable OLE1 DDE.
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100 | 0x400  # NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI (UAC still appears).
    info.lpVerb = "runas"
    info.lpFile = _powershell()
    info.lpParameters = subprocess.list2cmdline([
        "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded(_compressed_script_bootstrap(script))])
    info.nShow = 0  # SW_HIDE: the helper console, not the Windows consent dialog.
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise _native_error()
        if not info.hProcess:
            raise OSError("Elevation process unavailable")
        wait = kernel.WaitForSingleObject(info.hProcess, int(timeout * 1000))
        if wait == 0x102:
            # Do not terminate an elevated transaction halfway through rollback.
            raise subprocess.TimeoutExpired("Windows firewall permission", timeout)
        if wait != 0:
            raise _native_error()
        code = ctypes.c_uint32()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise _native_error()
        return code.value
    finally:
        if info.hProcess:
            kernel.CloseHandle(info.hProcess)
        if initialized in (0, 1):
            ole.CoUninitialize()


def _address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError("A private LAN IPv4 is required")
    return str(address)


def _quoted(value):
    return "'" + value.replace("'", "''") + "'"


def _encoded(script):
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _compressed_script_bootstrap(script):
    payload = base64.b64encode(gzip.compress(script.encode("utf-8"), mtime=0)).decode("ascii")
    return """
$ErrorActionPreference = 'Stop'
$bytes = [Convert]::FromBase64String('PAYLOAD')
$memory = [IO.MemoryStream]::new($bytes, $false)
$gzip = [IO.Compression.GZipStream]::new($memory, [IO.Compression.CompressionMode]::Decompress)
$reader = [IO.StreamReader]::new($gzip, [Text.Encoding]::UTF8)
try { & ([scriptblock]::Create($reader.ReadToEnd())) }
finally { $reader.Dispose(); $gzip.Dispose(); $memory.Dispose() }
""".replace("PAYLOAD", payload)


def _powershell():
    return ntpath.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _program():
    return ntpath.abspath(sys.executable)


def _rule_name(program, address):
    digest = hashlib.sha256((ntpath.normcase(program) + "\0" + address).encode("utf-8")).hexdigest()[:24]
    return "watch2notif-lan-" + digest


def _rule_description(program, address):
    return "One-use encrypted LAN pairing; listener closes after two minutes. Rule: " + _rule_name(program, address)


def _substitute(script, values):
    # A single pass never substitutes a placeholder-looking word inside an
    # inserted path, even when the filename contains NAME, ADDRESS or $().
    pattern = r"\b(?:" + "|".join(re.escape(key) for key in values) + r")\b"
    return re.sub(pattern, lambda match: values[match.group(0)], script)


def _run(script, timeout):
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded(_compressed_script_bootstrap(script))],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW, check=False)


def _probe_script(program, address):
    return _substitute(r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$program = PROGRAM
$description = DESCRIPTION
$policy = New-Object -ComObject HNetCfg.FwPolicy2
$profiles = [int]$policy.CurrentProfileTypes
$blockedAll = $false
$enabled = $false
foreach ($profile in @(1, 2, 4)) {
    if (($profiles -band $profile) -ne 0 -and $policy.FirewallEnabled($profile)) {
        $enabled = $true
        if ($policy.BlockAllInboundTraffic($profile)) { $blockedAll = $true }
    }
}
$rules = @()
foreach ($rule in $policy.Rules) {
    if ($rule.ApplicationName -ieq $program -and $rule.Enabled -and $rule.Direction -eq 1) {
        $rules += [pscustomobject]@{
            owned=($rule.Description -eq $description); profiles=[int]$rule.Profiles;
            action=[int]$rule.Action; protocol=[int]$rule.Protocol;
            local=[string]$rule.LocalAddresses; remote=[string]$rule.RemoteAddresses;
            ports=[string]$rule.LocalPorts; service=[string]$rule.ServiceName; edge=[bool]$rule.EdgeTraversal
        }
        if ($rules.Count -ge 64) { break }
    }
}
[pscustomobject]@{profiles=$profiles; enabled=$enabled; block_all=$blockedAll; rules=$rules;
    public_enabled=[bool]$policy.FirewallEnabled(4); public_default=[int]$policy.DefaultInboundAction(4)} |
    ConvertTo-Json -Compress -Depth 5
""", {"PROGRAM": _quoted(program), "DESCRIPTION": _quoted(_rule_description(program, address))})


def _local_matches(scope, address):
    for item in scope.split(","):
        item = item.strip()
        if item in ("*", "Any", address):
            return True
        try:
            if ipaddress.IPv4Address(address) in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            pass
    return False


def _single_host_scope(scope, address):
    try:
        network = ipaddress.ip_network(scope.strip(), strict=False)
        return network.version == 4 and network.num_addresses == 1 and network.network_address == ipaddress.IPv4Address(address)
    except ValueError:
        return False


def _local_subnet_scope(scope):
    items = set(re.split(r"[,\s]+", scope.strip()))
    return bool(items) and items <= {"LocalSubnet", "LocalSubnet4", "LocalSubnet6"} and bool(items & {"LocalSubnet", "LocalSubnet4"})


def _diagnosis(data, address):
    profiles = int(data["profiles"])
    active = [name for bit, name in ((1, "domain"), (2, "private"), (4, "public")) if profiles & bit]
    profile = active[0] if len(active) == 1 else "mixed" if active else "unknown"
    result = {"state": "unknown", "reason": "rule_missing", "profile": profile, "repairable": False}
    if data.get("block_all"):
        return {**result, "state": "blocked", "reason": "block_all"}
    configured = False
    blocking = []
    for rule in data.get("rules", []):
        # Only unrestricted TCP ports can definitively cover any pairing port.
        if not (int(rule.get("profiles", 0)) & profiles) or rule.get("protocol") not in (6, 256):
            continue
        if rule.get("ports", "") not in ("", "*", "Any") or rule.get("service", ""):
            continue
        if not _local_matches(rule.get("local", ""), address):
            continue
        if rule.get("remote", "") not in ("*", "Any") and not _local_subnet_scope(rule.get("remote", "")):
            continue
        if rule.get("action") == 0:
            blocking.append(rule.get("profiles") == 4 and rule.get("protocol") == 6
                            and rule.get("local") in ("*", "Any")
                            and rule.get("remote") in ("*", "Any"))
        if rule.get("owned") and rule.get("action") == 1:
            configured |= (rule.get("protocol") == 6 and _single_host_scope(rule.get("local", ""), address)
                           and _local_subnet_scope(rule.get("remote", "")) and rule.get("profiles") == 6
                           and not rule.get("edge", False))
    if blocking:
        return {**result, "state": "blocked", "reason": "explicit_block",
                "repairable": all(blocking) and data.get("public_default", 0) == 0 and data.get("public_enabled", True)}
    if configured:
        return {**result, "state": "allowed", "reason": "configured"}
    # Other policies, remote-address filters and third-party firewalls can
    # affect reachability. Absence of our rule is not a definitive block.
    return result


def status(address):
    supported = sys.platform == "win32"
    configurable = supported and bool(getattr(sys, "frozen", False)) and ntpath.splitext(sys.executable)[1].lower() == ".exe"
    result = {"supported": supported, "can_configure": configurable,
              "state": "unknown", "profile": "unknown", "reason": "not_windows", "repairable": False}
    if not supported:
        return result
    try:
        address = _address(address)
        process = _run(_probe_script(_program(), address), timeout=10)
        if process.returncode or len(process.stdout) > 65536:
            raise ValueError("Probe unavailable")
        result.update(_diagnosis(json.loads(process.stdout.lstrip("\ufeff")), address))
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        result["reason"] = "probe_failed"
    if not configurable:
        result["reason"] = "development"
    if result["reason"] == "block_all" or (result["reason"] == "explicit_block" and not result["repairable"]) or result["profile"] == "domain":
        result["can_configure"] = False
    return result


def _allow_script(program, address):
    name = _rule_name(program, address)
    return _substitute(r"""
$ErrorActionPreference = 'Stop'
$failureCode = 10
$created = $false
$disabled = New-Object 'System.Collections.Generic.List[string]'
function Get-RuleScope($rule) {
    $application = $rule | Get-NetFirewallApplicationFilter -ErrorAction Stop
    $ports = $rule | Get-NetFirewallPortFilter -ErrorAction Stop
    $addresses = $rule | Get-NetFirewallAddressFilter -ErrorAction Stop
    $service = $rule | Get-NetFirewallServiceFilter -ErrorAction Stop
    return @{
        program=[string]$application.Program; protocol=[string]$ports.Protocol;
        ports=[string]$ports.LocalPort; remote_ports=[string]$ports.RemotePort;
        local=[string]$addresses.LocalAddress; remote=[string]$addresses.RemoteAddress;
        service=[string]$service.Service
    }
}
function Get-ActiveTcpBlocks($snapshot) {
    return @($snapshot.rules | Where-Object {
        $_.action -eq 0 -and $_.protocol -in @(6,256) -and
        ($_.profiles -band $snapshot.profiles) -ne 0 -and $_.ports -in @('', '*', 'Any')
    })
}
function Test-SingleHost($scope) {
    return ([string]$scope).Trim() -in @(ADDRESS, ADDRESS32, ADDRESSMASK)
}
function Test-LocalSubnet($scope) {
    $items = @([regex]::Split(([string]$scope).Trim(), '[,\s]+'))
    foreach ($item in $items) { if ($item -notin @('LocalSubnet','LocalSubnet4','LocalSubnet6')) { return $false } }
    return ($items -contains 'LocalSubnet' -or $items -contains 'LocalSubnet4')
}
try {
    # Recheck after UAC: block-all and managed/scoped application blocks are
    # never weakened. Only exact Public-only broad TCP blocks are repairable.
    $before = & { PROBE } | ConvertFrom-Json
    if ($before.block_all -or $before.profiles -eq 1) { throw 'Managed or blocked profile' }
    $activeBlocks = @(Get-ActiveTcpBlocks $before)
    if ($activeBlocks.Count -and ($before.public_default -ne 0 -or -not $before.public_enabled)) {
        throw 'Public policy must remain deny-by-default'
    }
    foreach ($block in $activeBlocks) {
        if ($block.profiles -ne 4 -or $block.protocol -ne 6 -or
            $block.local -notin @('*', 'Any') -or $block.remote -notin @('*', 'Any') -or
            $block.service -ne '') { throw 'Scoped or managed block requires manual review' }
    }
    $failureCode = 11
    $candidates = @()
    # PersistentStore restricts candidates to local rules, excluding GPO.
    $filters = @(Get-NetFirewallApplicationFilter -PolicyStore PersistentStore -Program PROGRAM -ErrorAction Stop)
    foreach ($application in $filters) {
        if ($application.Program -ine PROGRAM) { continue }
        foreach ($rule in @($application | Get-NetFirewallRule -ErrorAction Stop)) {
            if ([string]$rule.Enabled -ne 'True' -or [string]$rule.Direction -ne 'Inbound' -or
                [string]$rule.Action -ne 'Block' -or [int]$rule.Profile -ne 4) { continue }
            $scope = Get-RuleScope $rule
            if ($scope.program -ieq PROGRAM -and $scope.protocol -in @('TCP', '6') -and
                $scope.ports -in @('Any', '*') -and $scope.remote_ports -in @('Any', '*') -and
                $scope.local -in @('Any', '*') -and $scope.remote -in @('Any', '*') -and
                $scope.service -in @('Any', '')) { $candidates += $rule }
        }
    }
    if ($candidates.Count -ne $activeBlocks.Count) { throw 'Block is not a repairable local rule' }
    $failureCode = 12
    $existing = Get-NetFirewallRule -PolicyStore PersistentStore -Name NAME -ErrorAction SilentlyContinue
    if ($existing) {
        $scope = Get-RuleScope $existing
        if ([string]$existing.Enabled -ne 'True' -or [string]$existing.Direction -ne 'Inbound' -or
            [string]$existing.Action -ne 'Allow' -or [int]$existing.Profile -ne 6 -or
            $scope.program -ine PROGRAM -or $scope.protocol -notin @('TCP','6') -or
            -not (Test-SingleHost $scope.local) -or -not (Test-LocalSubnet $scope.remote) -or
            $scope.ports -notin @('Any','*') -or $scope.remote_ports -notin @('Any','*') -or
            $scope.service -notin @('Any','') -or [string]$existing.EdgeTraversalPolicy -ne 'Block' -or
            $existing.Description -ne DESCRIPTION) { throw 'Existing owned rule was edited' }
    } else {
        $failureCode = 13
        New-NetFirewallRule -PolicyStore PersistentStore -Name NAME `
            -DisplayName 'watch2notif - local encrypted configuration' -Group 'watch2notif' `
            -Description DESCRIPTION `
            -Enabled True -Direction Inbound -Action Allow -Protocol TCP `
            -Program PROGRAM -LocalAddress ADDRESS -RemoteAddress LocalSubnet `
            -Profile Public,Private -EdgeTraversalPolicy Block -ErrorAction Stop | Out-Null
        $created = $true
    }
    # The narrow replacement exists before the broad Public block is disabled.
    $failureCode = 14
    foreach ($rule in $candidates) {
        $disabled.Add([string]$rule.Name)
        Set-NetFirewallRule -PolicyStore PersistentStore -Name $rule.Name -Enabled False -ErrorAction Stop | Out-Null
    }
    $failureCode = 15
    $after = & { PROBE } | ConvertFrom-Json
    $verified = @($after.rules | Where-Object {
        $_.owned -and $_.action -eq 1 -and $_.protocol -eq 6 -and $_.profiles -eq 6 -and
        (Test-SingleHost $_.local) -and (Test-LocalSubnet $_.remote) -and $_.ports -in @('', '*', 'Any') -and
        $_.service -eq '' -and -not $_.edge
    })
    if ($after.block_all -or $verified.Count -ne 1 -or @(Get-ActiveTcpBlocks $after).Count -ne 0) {
        throw 'Effective rule could not be verified'
    }
    exit 0
} catch {
    # Restore only rules this operation disabled. Rollback does not touch UDP,
    # Private/Domain, GPO, other applications or pre-existing owned allow rules.
    foreach ($ruleName in $disabled) {
        try { Set-NetFirewallRule -PolicyStore PersistentStore -Name $ruleName -Enabled True -ErrorAction Stop | Out-Null }
        catch { $failureCode = 16 }
    }
    if ($created) {
        try { Remove-NetFirewallRule -PolicyStore PersistentStore -Name NAME -ErrorAction Stop | Out-Null }
        catch { $failureCode = 16 }
    }
    exit $failureCode
}
""", {"PROGRAM": _quoted(program), "ADDRESS": _quoted(address), "NAME": _quoted(name),
       "ADDRESS32": _quoted(address + "/32"), "ADDRESSMASK": _quoted(address + "/255.255.255.255"),
       "DESCRIPTION": _quoted(_rule_description(program, address)), "PROBE": _probe_script(program, address)})


def allow(address):
    """User-click operation. Do not invoke automatically while starting a QR."""
    if sys.platform != "win32":
        return {"ok": False, "error": "unsupported"}
    if not getattr(sys, "frozen", False) or ntpath.splitext(sys.executable)[1].lower() != ".exe":
        return {"ok": False, "error": "development"}
    try:
        address = _address(address)
    except (ValueError, TypeError):
        return {"ok": False, "error": "invalid_address"}
    current = status(address)
    if current["reason"] == "block_all" or (current["reason"] == "explicit_block" and not current.get("repairable")):
        return {"ok": False, "error": current["reason"], "status": current}
    if current["profile"] == "domain":
        return {"ok": False, "error": "managed_network", "status": current}
    try:
        code = _elevate(_allow_script(_program(), address), timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except OSError as error:
        return {"ok": False, "error": "cancelled" if getattr(error, "winerror", None) == 1223 else "elevation_failed"}
    if code:
        return {"ok": False, "error": ELEVATION_ERRORS.get(code, "denied")}
    current = status(address)
    return {"ok": current["state"] == "allowed", "error": "verification_failed" if current["state"] != "allowed" else "",
            "status": current}
