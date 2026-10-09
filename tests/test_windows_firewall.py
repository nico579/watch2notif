import base64
import ctypes
import gzip
import json
import re
import subprocess
import sys
import unittest
from unittest import mock

import windows_firewall as firewall


class WindowsFirewallTests(unittest.TestCase):
    ADDRESS = "192.168.1.13"
    PROGRAM = r"C:\Users\Nico\Programs\watch2notif\watch2notif.exe"

    def windows(self):
        patches = [mock.patch.object(firewall.sys, "platform", "win32"),
                   mock.patch.object(firewall.sys, "frozen", True, create=True),
                   mock.patch.object(firewall.sys, "executable", self.PROGRAM)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_only_private_ipv4_addresses_are_accepted(self):
        for address in ("127.0.0.1", "169.254.1.2", "8.8.8.8", "::1", "192.168.1.13;evil", "172.32.1.1"):
            with self.assertRaises(ValueError):
                firewall._address(address)
        self.assertEqual(firewall._address(self.ADDRESS), self.ADDRESS)

    def test_rule_is_scoped_to_executable_one_address_local_subnet_tcp_and_non_domain_profiles(self):
        script = firewall._allow_script(self.PROGRAM, self.ADDRESS)
        self.assertIn("-Program '" + self.PROGRAM + "'", script)
        self.assertIn("-LocalAddress '192.168.1.13'", script)
        self.assertIn("-RemoteAddress LocalSubnet", script)
        self.assertIn("-Protocol TCP", script)
        self.assertIn("-Profile Public,Private", script)
        self.assertIn("-EdgeTraversalPolicy Block", script)
        self.assertNotIn("Set-NetConnectionProfile", script)
        self.assertNotIn("Set-NetFirewallProfile", script)
        self.assertNotIn("-Profile Any", script)
        self.assertEqual(script.count("Remove-NetFirewallRule -PolicyStore PersistentStore -Name 'watch2notif-lan-"), 1)

    def test_rule_name_is_stable_for_same_executable_and_address(self):
        name = firewall._rule_name(self.PROGRAM, self.ADDRESS)
        self.assertEqual(name, firewall._rule_name(self.PROGRAM.upper(), self.ADDRESS))
        self.assertNotEqual(name, firewall._rule_name(self.PROGRAM, "192.168.1.14"))
        self.assertNotEqual(name, firewall._rule_name(r"C:\other.exe", self.ADDRESS))

    def test_normalized_firewall_scopes_still_restrict_to_one_ipv4_and_local_subnet(self):
        for scope in (self.ADDRESS, self.ADDRESS + "/32", self.ADDRESS + "/255.255.255.255", self.ADDRESS + "-" + self.ADDRESS):
            self.assertTrue(firewall._single_host_scope(scope, self.ADDRESS))
        for scope in (self.ADDRESS + "/24", "192.168.1.14", "*", self.ADDRESS + ",192.168.1.14",
                      "192.168.1.1-192.168.1.255", "192.168.1.14-192.168.1.14", "192.168.1.13-", "192.168.1.13-192.168.1.13-192.168.1.13"):
            self.assertFalse(firewall._single_host_scope(scope, self.ADDRESS))
        for scope in ("LocalSubnet", "LocalSubnet4", "LocalSubnet4,LocalSubnet6", "LocalSubnet4 LocalSubnet6"):
            self.assertTrue(firewall._local_subnet_scope(scope))
        for scope in ("*", "Any", "", "LocalSubnet6", "LocalSubnet4,Internet"):
            self.assertFalse(firewall._local_subnet_scope(scope))

    def test_quotes_are_literal_without_script_file(self):
        script = firewall._allow_script(r"C:\Nico's $(evil)\watch2notif.exe", self.ADDRESS)
        self.assertIn("'C:\\Nico''s $(evil)\\watch2notif.exe'", script)
        self.assertEqual(base64.b64decode(firewall._encoded(script)).decode("utf-16le"), script)
        self.assertNotIn("-File ", script)

    def test_compressed_bootstrap_round_trips_unicode_without_files(self):
        script = firewall._allow_script(r"C:\Été NAME $(literal) Nico's\watch2notif.exe", self.ADDRESS)
        bootstrap = firewall._compressed_script_bootstrap(script)
        payload = re.search(r"FromBase64String\('([^']+)'\)", bootstrap).group(1)
        self.assertEqual(gzip.decompress(base64.b64decode(payload)).decode("utf-8"), script)
        self.assertIn("[scriptblock]::Create", bootstrap)
        self.assertNotIn("-File", bootstrap)

    def test_probe_and_mocked_script_stay_within_windows_command_limit(self):
        program = "C:\\" + ("NAME É $(literal) " * 100) + "watch2notif.exe"
        inner = firewall._allow_script(program, self.ADDRESS)
        for script in (inner, inner + inner):
            with mock.patch.object(firewall.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as runner:
                firewall._run(script, timeout=10)
                self.assertLess(len(subprocess.list2cmdline(runner.call_args.args[0])), 32767)

    def test_placeholder_words_in_path_are_not_substituted_a_second_time(self):
        program = r"C:\NAME ADDRESS PROGRAM DESCRIPTION $(literal) Nico's\watch2notif.exe"
        literal = "'" + program.replace("'", "''") + "'"
        self.assertIn("-Program " + literal, firewall._allow_script(program, self.ADDRESS))
        self.assertIn("$program = " + literal, firewall._probe_script(program, self.ADDRESS))

    @unittest.skipUnless(sys.platform == "win32", "PowerShell parsing and COM are Windows only")
    def test_powershell_templates_parse_without_running_their_commands(self):
        program = r"C:\NAME ADDRESS PROGRAM DESCRIPTION $(literal) Nico's\watch2notif.exe"
        scripts = [firewall._probe_script(program, self.ADDRESS), firewall._allow_script(program, self.ADDRESS)]
        for payload in scripts:
            parser = "$source = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + firewall._encoded(payload) + "')); $tokens = $null; $errors = $null; [void][Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors); if ($errors.Count) { Write-Output $errors; exit 1 }; exit 0"
            process = firewall._run(parser, timeout=10)
            self.assertEqual(process.returncode, 0, process.stdout)

    @unittest.skipUnless(sys.platform == "win32", "PowerShell parsing and COM are Windows only")
    def test_read_only_com_probe_returns_policy_without_modifying_it(self):
        process = firewall._run(firewall._probe_script(self.PROGRAM, self.ADDRESS), timeout=10)
        self.assertEqual(process.returncode, 0)
        import json
        data = json.loads(process.stdout.lstrip("\ufeff"))
        self.assertIsInstance(data["profiles"], int)
        self.assertIsInstance(data["block_all"], bool)
        self.assertIsInstance(data["rules"], list)

    @unittest.skipUnless(sys.platform == "win32", "Mocked PowerShell commands are Windows only")
    def test_allow_template_passes_only_narrow_parameters_to_mocked_netsecurity_commands(self):
        process, calls = self._mocked_allow()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        rule = next(call for call in calls if call.get("op") == "new")
        self.assertEqual(rule["Program"], self.PROGRAM)
        self.assertEqual(rule["LocalAddress"], self.ADDRESS)
        self.assertEqual(rule["RemoteAddress"], "LocalSubnet")
        self.assertEqual(rule["Protocol"], "TCP")
        self.assertEqual(rule["Profile"], ["Public", "Private"])
        self.assertEqual(rule["PolicyStore"], "PersistentStore")
        self.assertEqual(rule["Direction"], "Inbound")
        self.assertEqual(rule["Action"], "Allow")
        self.assertEqual(rule["EdgeTraversalPolicy"], "Block")
        self.assertEqual([call for call in calls if call.get("op") == "set"],
                         [{"op": "set", "Name": "public-tcp", "Enabled": "False"}])
        self.assertFalse(any(call.get("op") == "remove" for call in calls))

    @unittest.skipUnless(sys.platform == "win32", "Mocked PowerShell commands are Windows only")
    def test_public_tcp_repair_rolls_back_disabled_block_and_new_allow_on_failure(self):
        process, calls = self._mocked_allow(fail_disable=True)
        self.assertEqual(process.returncode, 14)
        self.assertEqual([call for call in calls if call.get("op") == "set"], [
            {"op": "set", "Name": "public-tcp", "Enabled": "False"},
            {"op": "set", "Name": "public-tcp", "Enabled": "True"}])
        self.assertEqual([call for call in calls if call.get("op") == "remove"],
                         [{"op": "remove", "Name": firewall._rule_name(self.PROGRAM, self.ADDRESS)}])

    @unittest.skipUnless(sys.platform == "win32", "Mocked PowerShell commands are Windows only")
    def test_windows_single_address_range_does_not_roll_back_a_valid_permission(self):
        process, calls = self._mocked_allow(local_scope=self.ADDRESS + "-" + self.ADDRESS)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertFalse(any(call.get("op") == "remove" for call in calls))
        self.assertEqual([call for call in calls if call.get("op") == "set"],
                         [{"op": "set", "Name": "public-tcp", "Enabled": "False"}])

    def _mocked_allow(self, fail_disable=False, local_scope=None):
        # Every NetSecurity cmdlet and both COM snapshots are replaced. This
        # executes template logic on Windows CI, without UAC or policy changes.
        common = dict(owned=False, action=0, protocol=6, local="*", remote="*", ports="*", service="")
        before = dict(profiles=6, enabled=True, public_enabled=True, public_default=0, block_all=False, rules=[dict(common, profiles=4),
            dict(common, profiles=4, protocol=17), dict(common, profiles=2, action=1)])
        after = dict(before, rules=[dict(common, profiles=4, protocol=17),
            dict(common, owned=True, profiles=6, action=1, local=local_scope or self.ADDRESS, remote="LocalSubnet")])
        probe = "$script:probeCount++; if ($script:probeCount -eq 1) { Write-Output " + firewall._quoted(json.dumps(before)) + " } else { Write-Output " + firewall._quoted(json.dumps(after)) + " }"
        rules = [dict(Name="public-tcp", Program=self.PROGRAM, Profile=4, Protocol="TCP", Action="Block"),
                 dict(Name="public-udp", Program=self.PROGRAM, Profile=4, Protocol="UDP", Action="Block"),
                 dict(Name="private-tcp", Program=self.PROGRAM, Profile=2, Protocol="TCP", Action="Allow"),
                 dict(Name="other-app", Program=r"C:\another.exe", Profile=4, Protocol="TCP", Action="Block")]
        setup = "$script:rules = " + firewall._quoted(json.dumps(rules)) + " | ConvertFrom-Json; $script:probeCount = 0; $script:failDisable = " + ("$true" if fail_disable else "$false") + "\n"
        stub = r"""
function Get-NetFirewallApplicationFilter {
    [CmdletBinding()] param($PolicyStore, $Program, [Parameter(ValueFromPipeline)]$InputObject)
    process {
        if ($InputObject) { return [pscustomobject]@{ Program=$InputObject.Program } }
        foreach ($rule in $script:rules) { [pscustomobject]@{Program=$rule.Program; RuleId=$rule.Name} }
    }
}
function Get-NetFirewallRule {
    [CmdletBinding()] param($PolicyStore, $Name, [Parameter(ValueFromPipeline)]$InputObject)
    process {
        if ($Name) { return $null }
        if ($InputObject) {
            foreach ($rule in $script:rules) {
                if ($rule.Name -eq $InputObject.RuleId) {
                    $rule | Add-Member -NotePropertyName Enabled -NotePropertyValue True -Force
                    $rule | Add-Member -NotePropertyName Direction -NotePropertyValue Inbound -Force
                    return $rule
                }
            }
        }
    }
}
function Get-NetFirewallPortFilter {
    [CmdletBinding()] param([Parameter(ValueFromPipeline)]$InputObject)
    process { [pscustomobject]@{ Protocol=$InputObject.Protocol; LocalPort='Any'; RemotePort='Any' } }
}
function Get-NetFirewallAddressFilter {
    [CmdletBinding()] param([Parameter(ValueFromPipeline)]$InputObject)
    process { [pscustomobject]@{ LocalAddress='Any'; RemoteAddress='Any' } }
}
function Get-NetFirewallServiceFilter {
    [CmdletBinding()] param([Parameter(ValueFromPipeline)]$InputObject)
    process { [pscustomobject]@{ Service='Any' } }
}
function New-NetFirewallRule {
    [CmdletBinding()] param($PolicyStore, $Name, $DisplayName, $Group, $Description,
        $Enabled, $Direction, $Action, $Protocol, $Program, $LocalAddress,
        $RemoteAddress, $Profile, $EdgeTraversalPolicy)
    $parameters = @{} + $PSBoundParameters; $parameters['op'] = 'new'
    [Console]::WriteLine(($parameters | ConvertTo-Json -Compress))
}
function Set-NetFirewallRule {
    [CmdletBinding()] param($PolicyStore, $Name, $Enabled)
    [Console]::WriteLine((@{op='set'; Name=$Name; Enabled=[string]$Enabled} | ConvertTo-Json -Compress))
    if ($script:failDisable -and [string]$Enabled -eq 'False') { throw 'Simulated failure' }
}
function Remove-NetFirewallRule {
    [CmdletBinding()] param($PolicyStore, $Name)
    [Console]::WriteLine((@{op='remove'; Name=$Name} | ConvertTo-Json -Compress))
}
"""
        with mock.patch.object(firewall, "_probe_script", return_value=probe):
            payload = setup + stub + firewall._allow_script(self.PROGRAM, self.ADDRESS)
        process = firewall._run(payload, timeout=10)
        calls = [json.loads(line) for line in process.stdout.splitlines() if line.startswith("{")]
        return process, calls

    def test_read_only_probe_cannot_change_firewall(self):
        script = firewall._probe_script(self.PROGRAM, self.ADDRESS)
        self.assertIn("HNetCfg.FwPolicy2", script)
        for mutation in ("New-NetFirewallRule", "Remove-NetFirewallRule", "Set-NetFirewall", "RunAs"):
            self.assertNotIn(mutation, script)

    def test_explicit_blocks_take_precedence_and_missing_rule_is_unknown(self):
        rule = dict(owned=True, profiles=6, action=1, protocol=6, local=self.ADDRESS,
                    remote="LocalSubnet", ports="*", service="")
        data = dict(profiles=4, enabled=True, block_all=False, rules=[rule])
        self.assertEqual(firewall._diagnosis(data, self.ADDRESS)["state"], "allowed")
        data["rules"].append(dict(rule, owned=False, action=0, local="*", remote="*"))
        self.assertEqual(firewall._diagnosis(data, self.ADDRESS)["reason"], "explicit_block")
        self.assertFalse(firewall._diagnosis(data, self.ADDRESS)["repairable"])
        data["rules"][-1]["profiles"] = 4
        self.assertTrue(firewall._diagnosis(data, self.ADDRESS)["repairable"])
        self.assertEqual(firewall._diagnosis(dict(data, rules=[]), self.ADDRESS)["state"], "unknown")
        self.assertEqual(firewall._diagnosis(dict(data, block_all=True), self.ADDRESS)["reason"], "block_all")

    def test_live_windows_range_snapshot_is_allowed_but_wider_ranges_are_not_owned_permissions(self):
        rule = dict(owned=True, profiles=6, action=1, protocol=6,
                    local=self.ADDRESS + "-" + self.ADDRESS, remote="LocalSubnet", ports="*", service="", edge=False)
        data = dict(profiles=6, enabled=True, block_all=False, rules=[rule])
        self.assertEqual(firewall._diagnosis(data, self.ADDRESS)["state"], "allowed")
        rule["local"] = "192.168.1.1-192.168.1.255"
        self.assertEqual(firewall._diagnosis(data, self.ADDRESS)["state"], "unknown")
        rule.update(owned=False, action=0, profiles=4)
        diagnosis = firewall._diagnosis(data, self.ADDRESS)
        self.assertEqual(diagnosis["reason"], "explicit_block")
        self.assertFalse(diagnosis["repairable"])

    def test_python_development_process_cannot_request_elevation(self):
        self.windows()
        with mock.patch.object(firewall.sys, "frozen", False), mock.patch.object(firewall, "_elevate") as runner:
            self.assertEqual(firewall.allow(self.ADDRESS), {"ok": False, "error": "development"})
            runner.assert_not_called()

    def test_non_windows_process_cannot_request_elevation(self):
        with mock.patch.object(firewall.sys, "platform", "linux"), mock.patch.object(firewall, "_elevate") as runner:
            self.assertEqual(firewall.allow(self.ADDRESS), {"ok": False, "error": "unsupported"})
            runner.assert_not_called()

    def test_allow_reports_uac_cancellation_without_exposing_output(self):
        self.windows()
        probe = {"state": "unknown", "reason": "rule_missing", "profile": "public"}
        error = OSError("private error"); error.winerror = 1223
        with mock.patch.object(firewall, "status", return_value=probe), mock.patch.object(firewall, "_elevate", side_effect=error):
            self.assertEqual(firewall.allow(self.ADDRESS), {"ok": False, "error": "cancelled"})

    def test_existing_block_is_reported_without_requesting_elevation(self):
        self.windows()
        probe = {"state": "blocked", "reason": "explicit_block", "profile": "public"}
        with mock.patch.object(firewall, "status", return_value=probe), mock.patch.object(firewall, "_elevate") as runner:
            self.assertEqual(firewall.allow(self.ADDRESS)["error"], "explicit_block")
            runner.assert_not_called()

    def test_success_is_reported_only_after_read_only_rule_verification(self):
        self.windows()
        before = {"state": "unknown", "reason": "rule_missing", "profile": "public"}
        after = {"state": "allowed", "reason": "configured", "profile": "public"}
        with mock.patch.object(firewall, "status", side_effect=[before, after]), mock.patch.object(firewall, "_elevate", return_value=0) as runner:
            result = firewall.allow(self.ADDRESS)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], after)
            self.assertIn("-RemoteAddress LocalSubnet", runner.call_args.args[0])

    def native(self, exit_code=0, wait=0):
        shell, kernel, ole = mock.Mock(), mock.Mock(), mock.Mock()
        ole.CoInitializeEx.return_value = 0
        kernel.WaitForSingleObject.return_value = wait
        def launch(pointer):
            pointer._obj.hProcess = 123
            return True
        def result(_handle, pointer):
            pointer._obj.value = exit_code
            return True
        shell.ShellExecuteExW.side_effect = launch
        kernel.GetExitCodeProcess.side_effect = result
        patch = mock.patch.object(firewall, "_winapi", return_value=(shell, kernel, ole))
        patch.start(); self.addCleanup(patch.stop)
        return shell, kernel, ole

    def test_native_uac_launch_is_hidden_unicode_bounded_and_closes_process_handle(self):
        shell, kernel, ole = self.native(exit_code=14)
        script = firewall._allow_script(r"C:\Été Nico's $(literal)\watch2notif.exe", self.ADDRESS)
        self.assertEqual(firewall._elevate(script, timeout=120), 14)
        info = shell.ShellExecuteExW.call_args.args[0]._obj
        self.assertEqual(info.cbSize, ctypes.sizeof(firewall._ShellExecuteInfo))
        self.assertEqual(info.lpVerb, "runas")
        self.assertEqual(info.lpFile, firewall._powershell())
        self.assertEqual(info.nShow, 0)
        self.assertEqual(info.fMask, 0x540)
        self.assertIn("-NoProfile -NonInteractive -EncodedCommand ", info.lpParameters)
        self.assertLess(len(info.lpFile) + len(info.lpParameters) + 3, 32767)
        payload = info.lpParameters.split()[-1]
        bootstrap = base64.b64decode(payload).decode("utf-16le")
        compressed = re.search(r"FromBase64String\('([^']+)'\)", bootstrap).group(1)
        self.assertEqual(gzip.decompress(base64.b64decode(compressed)).decode("utf-8"), script)
        kernel.WaitForSingleObject.assert_called_once_with(123, 120000)
        kernel.CloseHandle.assert_called_once_with(123)
        ole.CoUninitialize.assert_called_once_with()

    def test_native_timeout_closes_handle_and_does_not_terminate_transaction(self):
        _shell, kernel, ole = self.native(wait=0x102)
        with self.assertRaises(subprocess.TimeoutExpired): firewall._elevate("exit 0", timeout=5)
        kernel.CloseHandle.assert_called_once_with(123)
        kernel.TerminateProcess.assert_not_called()
        ole.CoUninitialize.assert_called_once_with()

    def test_native_uac_cancellation_is_distinct_and_balances_com(self):
        shell, kernel, ole = self.native()
        shell.ShellExecuteExW.side_effect = None
        shell.ShellExecuteExW.return_value = False
        with mock.patch.object(firewall, "_last_error", return_value=1223):
            with self.assertRaises(OSError) as raised: firewall._elevate("exit 0", timeout=5)
        self.assertEqual(raised.exception.winerror, 1223)
        kernel.CloseHandle.assert_not_called()
        ole.CoUninitialize.assert_called_once_with()

    def test_firewall_failure_stages_and_timeout_are_sanitized(self):
        self.windows()
        before = {"state": "unknown", "reason": "rule_missing", "profile": "public"}
        for code, error in {**firewall.ELEVATION_ERRORS, 99: "denied"}.items():
            with mock.patch.object(firewall, "status", return_value=before), mock.patch.object(firewall, "_elevate", return_value=code):
                self.assertEqual(firewall.allow(self.ADDRESS), {"ok": False, "error": error})
        with mock.patch.object(firewall, "status", return_value=before), mock.patch.object(firewall, "_elevate", side_effect=subprocess.TimeoutExpired("private command", 120)):
            self.assertEqual(firewall.allow(self.ADDRESS), {"ok": False, "error": "timeout"})


if __name__ == "__main__":
    unittest.main()
