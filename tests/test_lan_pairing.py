import base64
import concurrent.futures
import http.client
import json
import socket
import subprocess
import threading
import time
import unittest
from unittest import mock

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import lan_pairing


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PairingTests(unittest.TestCase):
    def session(self, lifetime=120):
        config = {"feeds": [], "credentials": {"anthropic_api_key": "dummy-private-test-key"}}
        session = lan_pairing.PairingSession(config, "127.0.0.1", lifetime)
        self.addCleanup(session.close)
        qr = json.loads(session.take_qr())
        return session, qr, config

    def request(self, session, code, **headers):
        connection = http.client.HTTPConnection("127.0.0.1", session.server.server_port, timeout=3)
        try:
            connection.request("POST", "/v1/config", json.dumps({"code": code}), headers={"Content-Type": "application/json", **headers})
            response = connection.getresponse()
            return response.status, response.read()
        finally: connection.close()

    def test_authenticated_ciphertext_round_trip_and_listener_closes(self):
        session, qr, config = self.session()
        status, body = self.request(session, qr["code"])
        self.assertEqual(status, 200)
        self.assertNotIn(b"dummy-private-test-key", body)
        self.assertNotIn(qr["key"].encode(), body)
        response = json.loads(body)
        decrypted = AESGCM(decode(qr["key"])).decrypt(decode(response["nonce"]), decode(response["ciphertext"]), lan_pairing.AAD)
        self.assertEqual(json.loads(decrypted), config)
        session.close()
        self.assertEqual(session.status()["state"], "used")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", session.server.server_port), timeout=0.5)

    def test_wrong_code_does_not_consume_the_session(self):
        session, qr, _ = self.session()
        self.assertEqual(self.request(session, "wrong")[0], 403)
        self.assertEqual(session.status()["state"], "ready")
        self.assertEqual(self.request(session, qr["code"])[0], 200)

    def test_concurrent_close_waits_until_listener_is_closed(self):
        session, _, _ = self.session()
        shutdown_started = threading.Event()
        release_shutdown = threading.Event()
        concurrent_close_waiting = threading.Event()
        shutdown = session.server.shutdown
        wait_for_close = session._close_complete.wait

        def delayed_shutdown():
            shutdown_started.set()
            if not release_shutdown.wait(timeout=3):
                raise TimeoutError("test did not release shutdown")
            shutdown()

        def observed_wait():
            concurrent_close_waiting.set()
            return wait_for_close(timeout=3)

        with mock.patch.object(session.server, "shutdown", side_effect=delayed_shutdown), \
                mock.patch.object(session._close_complete, "wait", side_effect=observed_wait), \
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first_close = pool.submit(session.close)
            second_close = None
            try:
                self.assertTrue(shutdown_started.wait(timeout=2))
                second_close = pool.submit(session.close)
                self.assertTrue(concurrent_close_waiting.wait(timeout=2))
                self.assertFalse(second_close.done())
            finally:
                release_shutdown.set()
            first_close.result(timeout=2)
            second_close.result(timeout=2)

        self.assertTrue(session._close_complete.is_set())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", session.server.server_port), timeout=0.5)

    def test_cross_origin_request_cannot_claim_the_transfer(self):
        session, qr, _ = self.session()
        self.assertEqual(self.request(session, qr["code"], Origin="https://evil.example")[0], 403)
        self.assertEqual(session.status()["state"], "ready")

    def test_wrong_host_or_content_type_cannot_consume_a_valid_ticket(self):
        session, qr, _ = self.session()
        self.assertEqual(self.request(session, qr["code"], Host="another-interface:1234")[0], 404)
        self.assertEqual(self.request(session, qr["code"], **{"Content-Type": "text/plain"})[0], 403)
        self.assertEqual(session.status()["state"], "ready")
        self.assertEqual(self.request(session, qr["code"])[0], 200)

    def test_expired_session_rejects_valid_code(self):
        session, qr, _ = self.session()
        session.deadline = time.monotonic() - 1
        self.assertEqual(self.request(session, qr["code"])[0], 410)

    def test_timer_closes_unused_listener(self):
        session, _, _ = self.session(lifetime=0.1)
        session.timer.join(timeout=2)
        self.assertEqual(session.status()["state"], "expired")
        self.assertEqual(session.response, b"")

    def test_only_one_of_simultaneous_claims_succeeds(self):
        session, qr, _ = self.session()
        def claim(_):
            try: return self.request(session, qr["code"])[0]
            except OSError: return 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(claim, range(8)))
        self.assertEqual(statuses.count(200), 1)

    def test_wrong_key_or_tampered_ciphertext_cannot_decrypt(self):
        session, qr, _ = self.session()
        response = json.loads(self.request(session, qr["code"])[1])
        nonce, ciphertext = decode(response["nonce"]), decode(response["ciphertext"])
        with self.assertRaises(InvalidTag): AESGCM(bytes(32)).decrypt(nonce, ciphertext, lan_pairing.AAD)
        damaged = bytearray(ciphertext); damaged[0] ^= 1
        with self.assertRaises(InvalidTag): AESGCM(decode(qr["key"])).decrypt(nonce, bytes(damaged), lan_pairing.AAD)

    def test_public_or_loopback_interface_is_not_exported_by_manager(self):
        with mock.patch.object(lan_pairing.platform, "system", return_value="Linux"), \
                mock.patch.object(socket, "socket", side_effect=OSError), \
                mock.patch.object(socket, "gethostbyname_ex", return_value=("pc", [], ["127.0.0.1", "8.8.8.8"])):
            with self.assertRaises(OSError): lan_pairing.local_address()

    def test_manager_generates_svg_qr_and_replaces_previous_listener(self):
        manager = lan_pairing.PairingManager()
        self.addCleanup(manager.close)
        with mock.patch.object(lan_pairing, "local_address", return_value="127.0.0.1"):
            first = manager.start({"feeds": []})
            self.assertTrue(first["qr_svg"].startswith("data:image/svg+xml;base64,"))
            svg = base64.b64decode(first["qr_svg"].split(",", 1)[1])
            self.assertIn(b"<svg", svg)
            previous = manager.session
            self.assertEqual(previous.qr, "")
            manager.start({"feeds": []})
            self.assertEqual(previous.status()["state"], "cancelled")
            with self.assertRaises(OSError): socket.create_connection(("127.0.0.1", previous.server.server_port), timeout=0.5)


class LocalInterfaceTests(unittest.TestCase):
    def windows_result(self, rows):
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(rows), stderr="")

    def test_windows_physical_interfaces_with_gateway_are_preferred_to_vpn_route(self):
        rows = [
            {"address": "192.168.2.10", "label": "Ethernet", "gateway": False, "network_category": "Private"},
            {"address": "192.168.1.13", "label": "Wi-Fi", "gateway": True, "network_category": "Public"},
        ]
        with mock.patch.object(lan_pairing.platform, "system", return_value="Windows"), \
                mock.patch.object(lan_pairing.subprocess, "run", return_value=self.windows_result(rows)) as run, \
                mock.patch.object(lan_pairing, "_fallback_candidates", side_effect=AssertionError("VPN/DNS fallback must not override physical interfaces")):
            candidates = lan_pairing.local_candidates()
            self.assertEqual(candidates[0], {"address": "192.168.1.13", "label": "Wi-Fi", "network_category": "public"})
            self.assertEqual(candidates[1]["network_category"], "private")
            arguments, options = run.call_args
            self.assertTrue(arguments[0][0].endswith("powershell.exe"))
            self.assertIn("-NoProfile", arguments[0])
            self.assertIn("-NonInteractive", arguments[0])
            script = arguments[0][-1]
            self.assertIn("Get-NetIPConfiguration -ErrorAction Stop", script)
            self.assertIn("HardwareInterface -ne $true", script)
            self.assertNotIn("-All", script)
            self.assertEqual(options["timeout"], 10)
            self.assertEqual(options["stdin"], subprocess.DEVNULL)
            self.assertEqual(options["creationflags"], getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_windows_candidates_deduplicate_and_reject_non_lan_addresses(self):
        rows = [
            {"address": "192.168.1.13", "label": " Wi-Fi\n ", "gateway": True, "network_category": "DomainAuthenticated"},
            {"address": "192.168.1.13", "label": "Alias", "gateway": False},
            *({"address": value} for value in ("127.0.0.1", "8.8.8.8", "0.0.0.0", "169.254.1.2", "100.64.1.2", "::1", "pc.example", "10.0.0.999")),
            {"address": "10.0.0.2", "label": "LAN", "gateway": False, "network_category": "unexpected"},
        ]
        with mock.patch.object(lan_pairing.subprocess, "run", return_value=self.windows_result(rows)):
            self.assertEqual(lan_pairing._windows_candidates(), [
                {"address": "192.168.1.13", "label": "Wi-Fi", "network_category": "domainauthenticated"},
                {"address": "10.0.0.2", "label": "LAN", "network_category": "unknown"},
            ])

    def test_windows_single_object_is_supported(self):
        row = {"address": "172.16.1.2", "label": "Ethernet", "gateway": True, "network_category": "Private"}
        with mock.patch.object(lan_pairing.subprocess, "run", return_value=self.windows_result(row)):
            self.assertEqual(lan_pairing._windows_candidates(), [
                {"address": "172.16.1.2", "label": "Ethernet", "network_category": "private"},
            ])

    def test_successful_windows_discovery_without_lan_does_not_choose_virtual_fallback(self):
        with mock.patch.object(lan_pairing.platform, "system", return_value="Windows"), \
                mock.patch.object(lan_pairing.subprocess, "run", return_value=self.windows_result([])), \
                mock.patch.object(lan_pairing, "_fallback_candidates", side_effect=AssertionError("No physical LAN should not choose VirtualBox")):
            self.assertEqual(lan_pairing.local_candidates(), [])
            with self.assertRaises(OSError): lan_pairing.local_address()

    def test_windows_timeout_or_invalid_output_uses_bounded_portable_fallback(self):
        fallback = [{"address": "192.168.1.13", "label": "192.168.1.13", "network_category": "unknown"}]
        failures = (subprocess.TimeoutExpired("powershell", 10), OSError("missing program"))
        with mock.patch.object(lan_pairing.platform, "system", return_value="Windows"), \
                mock.patch.object(lan_pairing, "_fallback_candidates", return_value=fallback):
            for failure in failures:
                with mock.patch.object(lan_pairing.subprocess, "run", side_effect=failure):
                    self.assertEqual(lan_pairing.local_candidates(), fallback)
            for output in ("not json", "null", "[" + " " * 65536 + "]"):
                result = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
                with mock.patch.object(lan_pairing.subprocess, "run", return_value=result):
                    self.assertEqual(lan_pairing.local_candidates(), fallback)

    def test_portable_discovery_filters_addresses_and_preserves_route_order(self):
        route = mock.MagicMock()
        route.__enter__.return_value.getsockname.return_value = ("10.0.0.2", 0)
        with mock.patch.object(lan_pairing.platform, "system", return_value="Darwin"), \
                mock.patch.object(socket, "socket", return_value=route), \
                mock.patch.object(socket, "gethostbyname_ex", return_value=("pc", [], ["10.0.0.2", "127.0.0.1", "192.168.1.13", "8.8.8.8", "broken"])), \
                mock.patch.object(lan_pairing.subprocess, "run", side_effect=AssertionError("No subprocess on portable fallback")):
            self.assertEqual([row["address"] for row in lan_pairing.local_candidates()], ["10.0.0.2", "192.168.1.13"])
            route.__enter__.return_value.connect.assert_called_once_with(("192.0.2.1", 9))

    def test_selected_interface_must_be_a_current_private_local_candidate(self):
        manager = lan_pairing.PairingManager()
        previous = mock.Mock()
        manager.session = previous
        candidates = [{"address": "192.168.1.13", "label": "Wi-Fi", "network_category": "public"}]
        with mock.patch.object(lan_pairing, "local_candidates", return_value=candidates), \
                mock.patch.object(lan_pairing, "PairingSession") as session:
            for address in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "192.168.1.99", "pc.example", "192.168.1.13; malicious", 13):
                with self.assertRaises(ValueError): manager.start({"feeds": []}, address)
            session.assert_not_called()
            previous.close.assert_not_called()

    def test_selected_interface_is_used_for_the_single_listener_and_qr_status(self):
        manager = lan_pairing.PairingManager()
        self.addCleanup(manager.close)
        candidates = [{"address": "192.168.1.13", "label": "Wi-Fi", "network_category": "public"},
                      {"address": "192.168.2.10", "label": "Ethernet", "network_category": "private"}]
        session = mock.Mock()
        session.take_qr.return_value = '{"type":"test-only"}'
        session.status.return_value = {"state": "ready", "expires_at": 123, "address": "192.168.2.10"}
        with mock.patch.object(lan_pairing, "local_candidates", return_value=candidates), \
                mock.patch.object(lan_pairing, "PairingSession", return_value=session) as create:
            self.assertEqual(manager.candidates(), candidates)
            result = manager.start({"feeds": []}, "192.168.2.10")
            create.assert_called_once_with({"feeds": []}, "192.168.2.10")
            self.assertEqual(result["address"], "192.168.2.10")
            self.assertTrue(result["qr_svg"].startswith("data:image/svg+xml;base64,"))


if __name__ == "__main__":
    unittest.main()
