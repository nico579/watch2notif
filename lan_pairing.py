"""Two-minute, single-use LAN transfer. The AES key only crosses via the QR.

The LAN response is authenticated AES-256-GCM ciphertext, not plaintext settings.
No permanent listener, log, file, token URL, cloud service or discovery broadcast.
"""
import atexit
import base64
import hmac
import io
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AAD = b"watch2notif-transfer-v1"
LIFETIME_SECONDS = 120


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def local_address() -> str:
    addresses = []
    # UDP connect selects an interface without sending a packet to this documentation address.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("192.0.2.1", 9))
            addresses.append(route.getsockname()[0])
    except OSError:
        pass
    try:
        addresses.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any(ip in ipaddress.ip_network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            return address
    raise OSError("No private IPv4 LAN interface available")


class PairingSession:
    def __init__(self, config: dict, address: str, lifetime: float = LIFETIME_SECONDS):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self.lock = threading.Lock()
        self.code = encode(secrets.token_bytes(32))
        self.address = address
        self.state = "ready"
        self._closed = False
        self._close_complete = threading.Event()
        self.deadline = time.monotonic() + lifetime
        self.expires_at = time.time() + lifetime
        key, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), AAD)
        self.response = json.dumps({"version": 1, "nonce": encode(nonce), "ciphertext": encode(ciphertext)}).encode("ascii")
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Never log a URL, peer, request body, authorization code or ciphertext.

            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def reply(self, status, body=b""):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                self.reply(404)

            def do_POST(self):
                if self.path != "/v1/config" or self.headers.get("Host") != f"{session.address}:{session.server.server_port}":
                    self.reply(404)
                    return
                # A browser cannot invoke this endpoint through an ordinary cross-origin form.
                if self.headers.get("Origin") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.reply(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024:
                        self.reply(400)
                        return
                    request = json.loads(self.rfile.read(length))
                    code = request.get("code", "")
                    if not isinstance(code, str) or not code.isascii():
                        self.reply(403)
                        return
                except (OSError, ValueError, AttributeError):
                    self.reply(400)
                    return
                with session.lock:
                    if session.state != "ready" or time.monotonic() >= session.deadline:
                        self.reply(410)
                        return
                    if not hmac.compare_digest(code, session.code):
                        self.reply(403)
                        return
                    response = session.response
                    session.state = "used"
                    session.code = ""
                    session.response = b""
                # Consumption happens before writing: a second simultaneous request cannot win.
                try:
                    self.reply(200, response)
                finally:
                    threading.Thread(target=session.close, args=("used",), daemon=True).start()

        self.server = ThreadingHTTPServer((address, 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()
        self.timer = threading.Timer(lifetime, self.close, args=("expired",))
        self.timer.daemon = True
        self.timer.start()
        # Key is intentionally not retained on the listener or included in the HTTP response.
        self.qr = json.dumps({"type": "watch2notif-pair", "version": 1,
                              "url": f"http://{address}:{self.server.server_port}/v1/config",
                              "code": self.code, "key": encode(key), "expires_at": self.expires_at}, separators=(",", ":"))

    def take_qr(self) -> str:
        payload, self.qr = self.qr, ""
        return payload

    def close(self, reason="cancelled"):
        with self.lock:
            shutdown_owner = not self._closed
            if shutdown_owner:
                self._closed = True
                if self.state == "ready":
                    self.state = reason
                self.code = ""
                self.response = b""
                self.qr = ""
        if not shutdown_owner:
            # A request may already be closing the listener asynchronously.
            # Every caller must wait for the port to close, outside the lock.
            self._close_complete.wait()
            return
        try:
            self.timer.cancel()
            try:
                self.server.shutdown()
            finally:
                self.server.server_close()
        finally:
            self._close_complete.set()

    def status(self) -> dict:
        with self.lock:
            return {"state": self.state, "expires_at": self.expires_at, "address": self.address}


class PairingManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None

    def start(self, config: dict) -> dict:
        import qrcode
        import qrcode.image.svg

        with self.lock:
            if self.session:
                self.session.close()
            session = PairingSession(config, local_address())
            self.session = session
            try:
                qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
                qr.add_data(session.take_qr())
                qr.make(fit=True)
                image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
                output = io.BytesIO()
                image.save(output)
                return {"ok": True, "qr_svg": "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii"), **session.status()}
            except Exception:
                session.close()
                raise

    def status(self):
        with self.lock:
            return self.session.status() if self.session else {"state": "closed"}

    def close(self):
        with self.lock:
            if self.session:
                self.session.close()


manager = PairingManager()
atexit.register(manager.close)
