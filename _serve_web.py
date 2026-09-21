"""Sert le GUI (gui/index.html + app.js + style.css) sur HTTP local, a la
place du panneau Qt (settings.py, retire - voir main_serve() dans
notifier.py).

Meme modele de securite que blink2video (serve.py, hote_autorise()) et
lidar2map (_serve_web.py, meme fonction) : pas d'authentification de
compte, seule la provenance de la requete (Host, adresse TCP du client,
Origin) est verifiee - un outil personnel, pas un service multi-
utilisateur. stdlib pur (http.server.ThreadingHTTPServer), pas de
framework (Flask/FastAPI), comme les deux autres.

Dispatch : une route ``/api/<clef>`` appelle ``api_routes["<clef>"]()`` en
GET ou ``post_routes["<clef>"](payload_json)`` en POST. Watch2notif n'a
pas besoin de parametres de requete (contrairement a lidar2map, ville/
dossier) : le dispatch generique GET couvre tous les cas.
"""
from __future__ import annotations

import ipaddress
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

_PREFIXE_API = "/api/"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Poses par demarrer() sur la CLASSE (une seule instance de serveur par
    # process, single_instance.py empeche tout doublon) avant de demarrer.
    trusted_host: str = ""
    gui_dir: Path | None = None
    api_routes: dict = {}
    post_routes: dict = {}

    _HOTES_LOCAUX = ("127.0.0.1", "localhost", "::1")

    def log_message(self, fmt, *args):
        pass  # pas de journal d'acces, rien d'utile ici

    # ------------------------------------------------------------ securite

    def hote_autorise(self) -> bool:
        """Calque direct de hote_autorise() dans blink2video/serve.py et
        lidar2map/_serve_web.py : faux si Host (declare par le client) ne
        designe pas cette machine, si l'adresse TCP reelle du client n'est
        ni la boucle locale ni le trusted_host, ou si Origin (quand le
        navigateur l'envoie) differe."""
        hote_confiance = (self.trusted_host or "").strip()
        hotes_valides = self._HOTES_LOCAUX + ((hote_confiance,) if hote_confiance else ())
        hote = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if hote not in hotes_valides:
            return False
        client = str(getattr(self, "client_address", ("127.0.0.1", 0))[0])
        try:
            boucle_locale = ipaddress.ip_address(client).is_loopback
        except ValueError:
            boucle_locale = False
        tunnel_direct = bool(hote_confiance) and hote == hote_confiance
        if not boucle_locale and not tunnel_direct:
            return False
        origine = self.headers.get("Origin")
        if origine:
            try:
                origine_hote = urlparse(origine).hostname
            except ValueError:
                origine_hote = None
            if origine_hote not in hotes_valides:
                return False
        return True

    # ------------------------------------------------------------- reponses

    def send_json(self, data, status: int = 200) -> None:
        corps = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def send_static(self, path: Path, content_type: str) -> None:
        try:
            corps = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    # --------------------------------------------------------------- GET

    def do_GET(self) -> None:
        if not self.hote_autorise():
            self.send_error(403)
            return
        # urlparse leve ValueError sur certaines formes manifestement
        # invalides (IPv6 mal ferme, ex. « //[abc ») - meme piege deja
        # corrige pour Origin dans hote_autorise() et pour self.path dans
        # blink2video/serve.py, jamais reporte ici jusqu'a cet audit.
        try:
            route = urlparse(self.path).path
        except ValueError:
            self.send_error(400)
            return

        if route == "/":
            self.send_static(self.gui_dir / "index.html", "text/html; charset=utf-8")
            return
        if route == "/app.js":
            self.send_static(self.gui_dir / "app.js", "text/javascript; charset=utf-8")
            return
        if route == "/style.css":
            self.send_static(self.gui_dir / "style.css", "text/css; charset=utf-8")
            return

        if not route.startswith(_PREFIXE_API):
            self.send_error(404)
            return
        gestionnaire = self.api_routes.get(route[len(_PREFIXE_API):])
        if gestionnaire is None:
            self.send_error(404)
            return
        self.send_json(gestionnaire())

    # --------------------------------------------------------------- POST

    def do_POST(self) -> None:
        if not self.hote_autorise():
            self.send_error(403)
            return
        try:
            route = urlparse(self.path).path
        except ValueError:
            self.send_error(400)
            return
        if not route.startswith(_PREFIXE_API):
            self.send_error(404)
            return
        gestionnaire = self.post_routes.get(route[len(_PREFIXE_API):])
        if gestionnaire is None:
            self.send_error(404)
            return
        try:
            longueur = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(400)
            return
        try:
            payload = json.loads(self.rfile.read(longueur) or b"{}")
        except json.JSONDecodeError:
            self.send_json({"error": "corps JSON illisible"}, 400)
            return
        self.send_json(gestionnaire(payload))


class Server(ThreadingHTTPServer):
    # Comportement Windows de allow_reuse_address : voir la meme
    # desactivation (et la meme raison) dans blink2video/serve.py.
    allow_reuse_address = os.name != "nt"


def demarrer(*, bind: str, port: int, trusted_host: str, gui_dir: Path,
             api_routes: dict, post_routes: dict | None = None) -> Server:
    """Cree et demarre le serveur (thread daemon, s'eteint avec le process).
    Retourne l'instance pour permettre server.shutdown()/server_close() par
    l'appelant. Leve OSError si le port est deja occupe."""
    Handler.trusted_host = trusted_host
    Handler.gui_dir = gui_dir
    Handler.api_routes = api_routes
    Handler.post_routes = post_routes or {}
    server = Server((bind, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
