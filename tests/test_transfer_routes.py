"""Exercise the desktop HTTP routes and encrypted LAN handoff with dummy keys.

No real configuration, credentials, autostart or LAN interface is used.
The listener is bound to loopback and every configuration file is temporary.
"""
import base64
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import lan_pairing
import notifier


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class TransferRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for patch in (
            mock.patch.object(notifier.data_paths, "DATA_DIR", self.directory),
            mock.patch.object(notifier, "CONFIG_FILE", self.directory / "config.json"),
            mock.patch.object(notifier, "STATE_DIR", self.directory / "state"),
            mock.patch.object(notifier.notification_history, "HISTORY_FILE", self.directory / "history.json"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.original = {"poll_interval_seconds": 60, "feeds": [], "lang": "fr"}
        notifier.save_config(self.original)
        self.manager = lan_pairing.PairingManager()
        self.addCleanup(self.manager.close)
        for patch in (
            mock.patch.object(lan_pairing, "manager", self.manager),
            mock.patch.object(lan_pairing, "local_address", return_value="127.0.0.1"),
            mock.patch.dict("os.environ", {
                "GITHUB_TOKEN": " dummy-github-key ",
                "YOUTUBE_API_KEY": " dummy-youtube-key ",
                "ANTHROPIC_API_KEY": " dummy-claude-key ",
            }),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        pause = threading.Event()
        get_routes, post_routes = notifier.build_api_routes(
            pause, notifier.SharedState(pause), threading.Event(),
        )
        self.server = notifier.serveweb.demarrer(
            bind="127.0.0.1", port=0, trusted_host="", gui_dir=notifier.GUI_DIR,
            api_routes=get_routes, post_routes=post_routes, favicon=notifier.ICON_FILE,
        )
        self.addCleanup(self.close_server)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read())

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return json.loads(response.read())

    def config(self):
        return {"feeds": [{
            "key": "questions", "label": "Questions", "kind": "rss",
            "url": "https://example.test/feed", "enabled": True,
            "interval_seconds": 60, "filtre_ia": "Only questions about Android",
            "ignored_private_field": "never-export-this",
        }], "credentials": {"anthropic_api_key": "client-must-not-override-key"},
            "history": [{"title": "never-export-this"}], "lang": "en"}

    def test_portable_json_preserves_claude_rule_and_omits_credentials(self):
        result = self.post("/api/validate-config", self.config())
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["config"]), {"poll_interval_seconds", "feeds"})
        self.assertEqual(result["config"]["feeds"][0]["filtre_ia"], "Only questions about Android")
        encoded = json.dumps(result)
        for private in ("never-export-this", "client-must-not-override-key", "dummy-claude-key"):
            self.assertNotIn(private, encoded)
        self.assertEqual(notifier.load_config(), self.original)
        self.assertIsNone(self.manager.session)

    def test_pair_start_only_exposes_credentials_inside_authenticated_ciphertext(self):
        captured = {}
        take_qr = lan_pairing.PairingSession.take_qr

        def capture_qr(session):
            payload = take_qr(session)
            captured.update(json.loads(payload))
            return payload

        with mock.patch.object(lan_pairing.PairingSession, "take_qr", capture_qr):
            result = self.post("/api/pair-start", self.config())
        self.assertTrue(result["ok"])
        self.assertTrue(result["qr_svg"].startswith("data:image/svg+xml;base64,"))
        self.assertNotIn("credentials", result)
        for private in ("dummy-github-key", "dummy-youtube-key", "dummy-claude-key"):
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual(self.get("/api/pair-status")["state"], "ready")
        request = urllib.request.Request(
            captured["url"], data=json.dumps({"code": captured["code"]}).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
        self.assertNotIn(b"dummy-claude-key", body)
        encrypted = json.loads(body)
        plaintext = AESGCM(decode(captured["key"])).decrypt(
            decode(encrypted["nonce"]), decode(encrypted["ciphertext"]), lan_pairing.AAD,
        )
        received = json.loads(plaintext)
        self.assertEqual(received["credentials"], {
            "github_token": "dummy-github-key", "youtube_api_key": "dummy-youtube-key",
            "anthropic_api_key": "dummy-claude-key",
        })
        self.assertEqual(received["feeds"][0]["filtre_ia"], "Only questions about Android")
        self.assertNotIn("never-export-this", plaintext.decode("utf-8"))
        self.manager.session.close()
        self.assertEqual(self.get("/api/pair-status")["state"], "used")
        self.assertEqual(notifier.load_config(), self.original)

    def test_invalid_config_never_opens_a_listener_or_changes_saved_sources(self):
        invalid = self.config()
        invalid["feeds"][0]["url"] = "file:///private"
        for route in ("/api/validate-config", "/api/pair-start"):
            self.assertEqual(self.post(route, invalid), {"ok": False, "error": "invalid_config"})
        self.assertIsNone(self.manager.session)
        self.assertEqual(notifier.load_config(), self.original)

    def test_pair_cancel_closes_the_listener(self):
        self.assertTrue(self.post("/api/pair-start", self.config())["ok"])
        port = self.manager.session.server.server_port
        self.assertEqual(self.post("/api/pair-cancel", {}), {"ok": True})
        self.assertEqual(self.get("/api/pair-status")["state"], "cancelled")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5)

    def test_network_failure_does_not_expose_tokens_or_modify_configuration(self):
        with mock.patch.object(lan_pairing, "local_address", side_effect=OSError("dummy-claude-key")):
            self.assertEqual(self.post("/api/pair-start", self.config()), {
                "ok": False, "error": "pair_unavailable",
            })
        self.assertIsNone(self.manager.session)
        self.assertEqual(notifier.load_config(), self.original)

    def test_network_choices_expose_interface_metadata_without_credentials(self):
        addresses = [{"address": "192.168.1.13", "label": "Wi-Fi", "network_category": "public"}]
        with mock.patch.object(self.manager, "candidates", return_value=addresses):
            result = self.get("/api/pair-network")
        self.assertEqual(result, {"ok": True, "addresses": addresses})
        self.assertNotIn("dummy-", json.dumps(result))
        self.assertIsNone(self.manager.session)

    def test_selected_interface_is_forwarded_and_client_credentials_are_ignored(self):
        payload = self.config()
        payload["address"] = "192.168.1.13"
        firewall = {"supported": True, "can_configure": True, "state": "unknown"}
        with mock.patch.object(self.manager, "start", return_value={"ok": True, "address": "192.168.1.13"}) as start, \
                mock.patch.object(notifier.windows_firewall, "status", return_value=firewall) as probe:
            self.assertEqual(self.post("/api/pair-start", payload), {"ok": True, "address": "192.168.1.13", "firewall": firewall})
        probe.assert_called_once_with("192.168.1.13")
        portable = start.call_args.args[0]
        self.assertEqual(start.call_args.kwargs, {"address": "192.168.1.13"})
        self.assertEqual(portable["credentials"]["anthropic_api_key"], "dummy-claude-key")
        self.assertNotIn("address", portable)

    def test_firewall_never_changes_on_start_or_network_probe(self):
        with mock.patch.object(notifier.windows_firewall, "allow") as allow:
            self.assertTrue(self.post("/api/pair-start", self.config())["ok"])
            with mock.patch.object(self.manager, "candidates", return_value=[]):
                self.get("/api/pair-network")
        allow.assert_not_called()

    def test_firewall_button_requires_active_session_and_uses_its_address(self):
        with mock.patch.object(notifier.windows_firewall, "allow", return_value={"ok": True}) as allow:
            self.assertEqual(self.post("/api/pair-allow", {}), {"ok": False, "error": "pair_expired"})
            allow.assert_not_called()
            self.assertTrue(self.post("/api/pair-start", self.config())["ok"])
            # A client-supplied address cannot widen the permission to another interface.
            self.assertEqual(self.post("/api/pair-allow", {"address": "0.0.0.0"}), {"ok": True})
            allow.assert_called_once_with("127.0.0.1")
            self.post("/api/pair-cancel", {})
            self.assertEqual(self.post("/api/pair-allow", {}), {"ok": False, "error": "pair_expired"})
            self.assertEqual(allow.call_count, 1)


if __name__ == "__main__":
    unittest.main()
