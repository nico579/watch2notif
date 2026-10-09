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
import os
import platform
import secrets
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AAD = b"watch2notif-transfer-v1"
LIFETIME_SECONDS = 120


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_WINDOWS_INTERFACES_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$rows = @(foreach ($configuration in Get-NetIPConfiguration -ErrorAction Stop) {
    if ($configuration.NetAdapter.Status -ne 'Up' -or $configuration.NetAdapter.HardwareInterface -ne $true) { continue }
    foreach ($ip in $configuration.IPv4Address) {
        [pscustomobject]@{
            address = [string]$ip.IPAddress
            label = [string]$configuration.InterfaceAlias
            gateway = @($configuration.IPv4DefaultGateway | Where-Object { $_.NextHop }).Count -gt 0
            network_category = [string]$configuration.NetProfile.NetworkCategory
        }
    }
})
ConvertTo-Json -InputObject $rows -Compress -Depth 3
"""


def _private_address(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(address in network for network in _PRIVATE_NETWORKS)


def _windows_candidates() -> list | None:
    """Read connected, non-virtual Windows interfaces without changing anything.

    Get-NetIPConfiguration without -All excludes virtual/disconnected adapters.
    None means discovery failed; an empty list means it succeeded with no LAN IP.
    """
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_INTERFACES_SCRIPT],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            timeout=10, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if len(result.stdout) > 65536:
            return None
        rows = json.loads(result.stdout.lstrip("\ufeff"))
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            return None
        candidates = []
        for row in rows:
            if not isinstance(row, dict) or not _private_address(row.get("address")):
                continue
            address = row["address"]
            label = " ".join(str(row.get("label") or address).split())[:128]
            category = str(row.get("network_category") or "").lower()
            if category not in {"public", "private", "domainauthenticated"}:
                category = "unknown"
            candidates.append({"address": address, "label": label, "network_category": category,
                               "gateway": row.get("gateway") is True})
        # Prefer a physical LAN with a gateway rather than a disconnected island.
        candidates.sort(key=lambda row: (not row["gateway"], row["label"].casefold(),
                                         int(ipaddress.IPv4Address(row["address"]))))
        unique, seen = [], set()
        for candidate in candidates:
            if candidate["address"] not in seen:
                seen.add(candidate["address"])
                unique.append({key: candidate[key] for key in ("address", "label", "network_category")})
        return unique
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return None


def _fallback_candidates() -> list:
    """Portable standard-library fallback; only literal private IPv4 is exposed."""
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
    candidates, seen = [], set()
    for address in addresses:
        if _private_address(address) and address not in seen:
            seen.add(address)
            candidates.append({"address": address, "label": address, "network_category": "unknown"})
    return candidates


def local_candidates() -> list:
    if platform.system() == "Windows":
        candidates = _windows_candidates()
        if candidates is not None:
            return candidates
    return _fallback_candidates()


def local_address() -> str:
    candidates = local_candidates()
    if candidates:
        return candidates[0]["address"]
    raise OSError("No private IPv4 LAN interface available")


class PairingSession:
    def __init__(self, config: dict, address: str, lifetime: float = LIFETIME_SECONDS):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self.lock = threading.Lock()
        self.code = encode(secrets.token_bytes(32))
        self.address = address
        self.state = "ready"
        self.connections = 0
        self.requests = 0
        self.last_result = "waiting"
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
                session.observe(connection=True)

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
                session.observe(request=True)
                if self.path != "/v1/config" or self.headers.get("Host") != f"{session.address}:{session.server.server_port}":
                    session.observe("wrong_endpoint")
                    self.reply(404)
                    return
                # A browser cannot invoke this endpoint through an ordinary cross-origin form.
                if self.headers.get("Origin") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    session.observe("request_rejected")
                    self.reply(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024:
                        session.observe("bad_request")
                        self.reply(400)
                        return
                    request = json.loads(self.rfile.read(length))
                    code = request.get("code", "")
                    if not isinstance(code, str) or not code.isascii():
                        session.observe("bad_code")
                        self.reply(403)
                        return
                except (OSError, ValueError, AttributeError):
                    session.observe("bad_request")
                    self.reply(400)
                    return
                with session.lock:
                    if session.state != "ready" or time.monotonic() >= session.deadline:
                        if session.state == "ready": session.last_result = "expired"
                        self.reply(410)
                        return
                    if not hmac.compare_digest(code, session.code):
                        session.last_result = "bad_code"
                        self.reply(403)
                        return
                    response = session.response
                    session.state = "used"
                    session.code = ""
                    session.response = b""
                # Consumption happens before writing: a second simultaneous request cannot win.
                try:
                    self.reply(200, response)
                    session.observe("sent")
                except OSError:
                    session.observe("write_failed")
                finally:
                    threading.Thread(target=session.close, args=("used",), daemon=True).start()

        class Server(ThreadingHTTPServer):
            def handle_error(self, *_args):
                # The default handler prints the peer and an arbitrary traceback.
                session.observe("request_rejected")

        self.server = Server((address, 0), Handler)
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
            return {"state": self.state, "expires_at": self.expires_at, "address": self.address,
                    "connections": self.connections, "requests": self.requests, "last_result": self.last_result}

    def observe(self, result=None, *, connection=False, request=False):
        # Bounded, in-memory diagnostics: no peer, URL, QR, code, body or key.
        with self.lock:
            if connection: self.connections = min(999, self.connections + 1)
            if request: self.requests = min(999, self.requests + 1)
            if result and (self.state == "ready" or result in ("sent", "write_failed")):
                self.last_result = result


class PairingManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None

    def candidates(self) -> list:
        return local_candidates()

    def start(self, config: dict, address: str | None = None) -> dict:
        import qrcode
        import qrcode.image.svg

        if address is None:
            address = local_address()
        elif not _private_address(address) or address not in {candidate["address"] for candidate in local_candidates()}:
            # An HTTP client cannot make us bind a public, wildcard or remote IP.
            raise ValueError("invalid local address")
        with self.lock:
            if self.session:
                self.session.close()
            session = PairingSession(config, address)
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

    def close(self, expected_expires_at=None):
        with self.lock:
            if expected_expires_at is not None:
                if not self.session:
                    return False
                current = self.session.status()
                if current["state"] != "ready" or current["expires_at"] != expected_expires_at:
                    return False
            if self.session:
                self.session.close()
            return True


manager = PairingManager()
atexit.register(manager.close)
