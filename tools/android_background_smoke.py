"""GitHub-emulator-only smoke: real service, deep sleep, process death and Android 15 quota."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET

PACKAGE = "io.github.nico579.watch2notif"
TAG = "watch2notif:fast-monitoring"


def adb(*arguments, timeout=30):
    result = subprocess.run(["adb", *arguments], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"ADB command failed: {arguments[0]}")
    return result.stdout.strip()


def shell(*arguments):
    return adb("shell", *arguments)


def wait_for(predicate, label, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (ValueError, ET.ParseError, RuntimeError):
            pass
        time.sleep(0.5)
    raise AssertionError(f"Timed out: {label}")


def preferences():
    root = ET.fromstring(shell("run-as", PACKAGE, "cat", "shared_prefs/monitoring.xml"))
    return {node.attrib["name"]: node.text if node.tag == "string" else node.attrib.get("value", "") for node in root}


def configuration():
    return json.loads(shell("run-as", PACKAGE, "cat", "files/watch2notif.json"))


def service_running():
    status = shell("dumpsys", "activity", "services", PACKAGE)
    return ".LivePollService" in status and "isForeground=true" in status


def cpu_held():
    return any(TAG in line and "PARTIAL_WAKE_LOCK" in line for line in shell("dumpsys", "power").splitlines())


def recorded_cycles():
    return int(preferences().get("cycles", "0"))


def successful_source():
    return configuration()["states"].get("ci-monitoring", {}).get("last_success", 0) > 0


def notified(title):
    history = configuration()["history"]
    return sum(row["title"] == title for row in history) == 1


def prepare_fixture():
    result = shell("am", "instrument", "-w", "-e", "class", PACKAGE + ".MonitoringFixtureTest",
                   PACKAGE + ".test/androidx.test.runner.AndroidJUnitRunner")
    assert "OK (1 test)" in result and "FAILURES" not in result, "Emulator fixture preparation failed"


def open_app():
    shell("input", "keyevent", "KEYCODE_WAKEUP")
    shell("wm", "dismiss-keyguard")
    shell("am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
    wait_for(service_running, "foreground service started from visible activity")
    wait_for(cpu_held, "partial wake lock acquired")


def automatic_scheduled():
    status = shell("dumpsys", "jobscheduler")
    return bool(re.search(r"JOB #[^\n]*" + re.escape(PACKAGE)
                          + r"/androidx\.work\.impl\.background\.systemjob\.SystemJobService", status))


class Fixture(BaseHTTPRequestHandler):
    entries = ["baseline"]
    requests = 0

    def do_GET(self):
        type(self).requests += 1
        body = ("<rss><channel>" + "".join("<item><guid>" + entry + "</guid><title>" + entry
                + "</title></item>" for entry in list(type(self).entries)) + "</channel></rss>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_arguments):
        pass


def main():
    assert os.environ.get("GITHUB_ACTIONS") == "true", "Run only on GitHub Actions, never on a user's phone"
    assert shell("getprop", "ro.kernel.qemu") == "1", "Only a disposable Android emulator is supported"
    sdk = int(shell("getprop", "ro.build.version.sdk"))
    assert sdk in (30, 35), "Expected the Android 11/15 CI matrix"
    adb("root")
    adb("wait-for-device")
    adb("install", "-r", "android/app/build/outputs/apk/debug/app-debug.apk", timeout=120)
    adb("install", "-r", "android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk", timeout=120)
    if sdk >= 33:
        shell("pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    adb("reverse", "tcp:29089", f"tcp:{server.server_port}")
    checks = []
    original_timeout = shell("device_config", "get", "activity_manager", "data_sync_fgs_timeout_duration")
    try:
        # Represents the user's explicit Android battery permission, on this disposable emulator only.
        shell("dumpsys", "deviceidle", "whitelist", "+" + PACKAGE)
        prepare_fixture()
        open_app()
        wait_for(successful_source, "quiet RSS baseline")
        assert not configuration()["history"], "Baseline must not notify"
        wait_for(automatic_scheduled, "automatic fallback remains scheduled")
        checks.append("foreground_and_quiet_baseline")

        shell("input", "keyevent", "KEYCODE_HOME")
        shell("input", "keyevent", "KEYCODE_SLEEP")
        shell("dumpsys", "battery", "unplug")
        shell("dumpsys", "deviceidle", "force-idle")
        assert shell("dumpsys", "deviceidle", "get", "deep") == "IDLE", "Device must actually enter deep sleep"
        Fixture.entries.append("new-in-deep-sleep")
        wait_for(lambda: notified("new-in-deep-sleep"), "native notification while screen is off and Doze is active")
        assert cpu_held() and service_running(), "Foreground monitoring must stay active during Doze"
        assert shell("dumpsys", "deviceidle", "get", "deep") == "IDLE", "Doze must still be active after delivery"
        checks.append("screen_off_doze_notification")

        previous_pid = shell("pidof", PACKAGE)
        assert re.fullmatch(r"[0-9]+", previous_pid), "Expected one app process"
        previous_cycles = recorded_cycles()
        shell("kill", "-9", previous_pid)
        wait_for(lambda: shell("pidof", PACKAGE) not in ("", previous_pid) and service_running(), "sticky process restart", timeout=90)
        wait_for(lambda: recorded_cycles() > previous_cycles, "polling resumes after process death")
        Fixture.entries.append("new-after-restart")
        wait_for(lambda: notified("new-after-restart"), "notification after sticky restart")
        assert len(configuration()["history"]) == 2, "Restart must not duplicate notifications or reseed history"
        assert cpu_held(), "Restart must reacquire the CPU lock"
        checks.append("sticky_restart_without_duplicates")

        shell("dumpsys", "deviceidle", "unforce")
        shell("dumpsys", "battery", "reset")
        shell("am", "startservice", "-n", PACKAGE + "/.LivePollService", "-a", "stop")
        wait_for(lambda: not service_running() and not cpu_held() and preferences().get("requested") == "false", "explicit stop releases CPU")
        wait_for(automatic_scheduled, "automatic work survives stopping fast mode")
        checks.append("explicit_stop_and_automatic_fallback")

        if sdk >= 35:
            shell("device_config", "put", "activity_manager", "data_sync_fgs_timeout_duration", "10000")
            prepare_fixture()
            open_app()
            shell("input", "keyevent", "KEYCODE_HOME")
            wait_for(lambda: preferences().get("interruption") == "limit" and not service_running() and not cpu_held(),
                     "real Android 15 foreground-service timeout", timeout=90)
            assert preferences().get("requested") == "true", "Timed-out session must remain visibly interrupted"
            wait_for(automatic_scheduled, "automatic fallback after quota exhaustion")
            time.sleep(3)
            assert not service_running(), "A timed-out session must not restart itself"
            checks.append("android15_real_timeout_and_fallback")

        report = {"sdk": sdk, "checks": checks, "fixture_requests": Fixture.requests, "failures": 0}
        output = Path(f"android/build/background-smoke-api-{sdk}.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
    finally:
        shell("dumpsys", "deviceidle", "unforce")
        shell("dumpsys", "battery", "reset")
        shell("dumpsys", "deviceidle", "whitelist", "-" + PACKAGE)
        if original_timeout == "null":
            shell("device_config", "delete", "activity_manager", "data_sync_fgs_timeout_duration")
        else:
            shell("device_config", "put", "activity_manager", "data_sync_fgs_timeout_duration", original_timeout)
        adb("reverse", "--remove", "tcp:29089")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
