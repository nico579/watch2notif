import base64
import concurrent.futures
import http.client
import json
import socket
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
        with mock.patch.object(socket, "socket", side_effect=OSError), mock.patch.object(socket, "gethostbyname_ex", return_value=("pc", [], ["127.0.0.1", "8.8.8.8"])):
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


if __name__ == "__main__":
    unittest.main()
