"""Tests de la migration Qt -> web+pystray : SharedState (remplace les
signaux Qt), build_feeds_from_rows (remplace SettingsWindow.on_save), les
routes HTTP reelles (build_api_routes + serveweb, sur un port ephemere
et un DATA_DIR temporaire - jamais les vraies donnees), et la construction
du tray (jamais icon.run(), voir la lecon de la migration lidar2map).

Piege connu (voir memoire feedback-migrer-donnees-installdir-piege-test) :
DOSSIERS.preparer_etat(INSTALL_DIR) lit INSTALL_DIR, jamais patchable,
qui pointe toujours vers le vrai dossier du projet. Aucun test ici
n'appelle notifier.main() ni preparer_etat() : build_api_routes
et _construire_tray suffisent a exercer le vrai code sans passer par elles.
"""
import builtins
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import notifier


class FauxVerificateur:
    """La dernière release connue (None : rien de plus récent)."""

    def __init__(self, version):
        self.version = version

    def disponible(self):
        return {"version": self.version, "page": "https://example.test", "assets": []} \
            if self.version else None


class FauxInstallateur:
    def __init__(self, possible=True, accepte=True):
        self._possible, self._accepte, self.demarre = possible, accepte, 0

    def possible(self):
        return (self._possible, "" if self._possible else "source_mode")

    def demarrer(self):
        if self._accepte:
            self.demarre += 1
        return self._accepte


class SharedStateTests(unittest.TestCase):
    def test_pas_d_etat_de_mise_a_jour_propre(self):
        # L'installation d'une mise à jour est conduite par l'Installateur du
        # commun (nico579_commons.maj_install, testé là-bas) ; l'état partagé
        # ne porte plus que la pause et l'accès à cet installateur.
        etat = notifier.SharedState(threading.Event())
        self.assertIsNone(etat.installateur)
        self.assertFalse(hasattr(etat, "update_status"))


class BuildFeedsFromRowsTests(unittest.TestCase):
    def test_blank_row_is_skipped(self):
        feeds = notifier.build_feeds_from_rows([
            {"label": "", "url": "", "enabled": False, "kind": "rss"},
            {"label": "Kept", "url": "https://example.test/a", "enabled": True, "kind": "rss", "interval_seconds": 60},
        ])
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0]["label"], "Kept")

    def test_duplicate_labels_get_suffixed_keys(self):
        rows = [
            {"key": "", "label": "Same", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60},
            {"key": "", "label": "Same", "url": "https://b.test", "enabled": False, "kind": "rss", "interval_seconds": 60},
        ]
        feeds = notifier.build_feeds_from_rows(rows)
        self.assertEqual([f["key"] for f in feeds], ["same", "same_2"])

    def test_existing_key_is_reused_not_reslugified(self):
        # Le client renvoie la clef deja assignee (stashee cote JS comme
        # checkbox._feed_key l'etait en Qt) : un renommage du label ne doit
        # jamais regenerer une nouvelle clef, sous peine de perdre
        # l'historique de dedup (state/<key>.json) de cette source.
        rows = [{"key": "my_source", "label": "Renamed", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60}]
        feeds = notifier.build_feeds_from_rows(rows)
        self.assertEqual(feeds[0]["key"], "my_source")

    def test_duplicate_explicit_key_is_reslugified_not_left_colliding(self):
        # Deux lignes qui partagent la meme clef EXPLICITE (frontend buggue,
        # ou payload construit a la main) : sans ce garde-fou, les deux
        # partagent le meme state_file(key) et s'ecrasent mutuellement le
        # fingerprint a chaque cycle, sans jamais notifier ni pour l'une ni
        # pour l'autre (trouve en audit).
        rows = [
            {"key": "dup", "label": "First", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60},
            {"key": "dup", "label": "Second", "url": "https://b.test", "enabled": True, "kind": "rss", "interval_seconds": 60},
        ]
        feeds = notifier.build_feeds_from_rows(rows)
        keys = [f["key"] for f in feeds]
        self.assertEqual(len(keys), len(set(keys)), "les deux flux ne doivent jamais partager la meme clef")
        self.assertEqual(keys[0], "dup")

    def test_missing_label_falls_back_to_key(self):
        feeds = notifier.build_feeds_from_rows([{"key": "", "label": "", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 60}])
        self.assertEqual(feeds[0]["label"], "source")

    def test_invalid_interval_falls_back_to_kind_default(self):
        feeds = notifier.build_feeds_from_rows([
            {"key": "", "label": "X", "url": "https://a.test", "enabled": True, "kind": "github_issues", "interval_seconds": None},
        ])
        expected = getattr(notifier.PROVIDERS["github_issues"], "DEFAULT_INTERVAL_SECONDS", 60)
        self.assertEqual(feeds[0]["interval_seconds"], expected)

    def test_unknown_kind_falls_back_to_default_kind(self):
        feeds = notifier.build_feeds_from_rows([
            {"key": "", "label": "X", "url": "https://a.test", "enabled": True, "kind": "not_a_real_kind", "interval_seconds": 60},
        ])
        self.assertEqual(feeds[0]["kind"], notifier.DEFAULT_KIND)


class TrayDisponibleTests(unittest.TestCase):
    def test_generic_exception_at_import_is_treated_as_unavailable(self):
        # Regression lidar2map (pystray sur Linux sans X11) : l'import de
        # pystray peut lever Xlib.error.DisplayNameError, un RuntimeError,
        # pas un ImportError. except Exception, pas except ImportError.
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pystray":
                raise RuntimeError("no X11 display")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            self.assertFalse(notifier._tray_disponible())


class HttpApiTests(unittest.TestCase):
    """Sert les vraies routes (build_api_routes) sur un port ephemere
    (port=0, l'OS choisit un port libre : jamais de collision possible
    avec une vraie instance ou un autre test parallele) et un DATA_DIR
    temporaire. autostart_manager entierement mocke : ce test ne doit
    jamais toucher le vrai dossier de demarrage Windows/systemd/launchd."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name) / "data"
        self.data_dir.mkdir()
        self.data_dir_patch = mock.patch.object(notifier.data_paths, "DATA_DIR", self.data_dir)
        self.config_file_patch = mock.patch.object(notifier, "CONFIG_FILE", self.data_dir / "config.json")
        self.state_dir_patch = mock.patch.object(notifier, "STATE_DIR", self.data_dir / "state")
        self.history_file_patch = mock.patch.object(
            notifier.notification_history, "HISTORY_FILE", self.data_dir / "notification_history.json",
        )
        for patch in (self.data_dir_patch, self.config_file_patch, self.state_dir_patch, self.history_file_patch):
            patch.start()

        self.autostart_enabled = False

        def _activer(_entree):
            self.autostart_enabled = True
            return []

        def _desactiver(_entree):
            self.autostart_enabled = False

        # La case de demarrage est celle du commun (nico579_commons.demarrage.routes) :
        # on simule ses trois gestes, jamais le vrai dossier Demarrage ni systemd.
        self.autostart_patch = mock.patch.multiple(
            notifier.demarrage,
            est_actif=lambda _entree: self.autostart_enabled,
            activer=_activer,
            desactiver=_desactiver,
        )
        self.autostart_patch.start()

        notifier.save_config(notifier.default_config())

        self.pause_event = threading.Event()
        self.state = notifier.SharedState(self.pause_event)
        self.stop_event = threading.Event()
        api_routes, post_routes = notifier.build_api_routes(self.pause_event, self.state, self.stop_event)
        self.server = notifier.serveweb.demarrer(
            bind="127.0.0.1", port=0, trusted_host="", gui_dir=notifier.GUI_DIR,
            api_routes=api_routes, post_routes=post_routes, favicon=notifier.ICON_FILE,
        )
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.autostart_patch.stop()
        for patch in (self.history_file_patch, self.state_dir_patch, self.config_file_patch, self.data_dir_patch):
            patch.stop()
        self.tempdir.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.read()

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())

    def _raw_request(self, request_bytes: bytes) -> bytes:
        # urllib normalise/rejette ce qu'on veut justement envoyer tel quel
        # (chemin manifestement invalide pour urlparse, en-tete non
        # numerique) : socket brut, seul moyen de reproduire une vraie
        # requete malformee comme un client bugue ou hostile pourrait
        # l'envoyer.
        # Un seul recv, pas une boucle jusqu'a fermeture : le serveur est
        # HTTP/1.1 (keep-alive par defaut), il ne fermera pas la connexion
        # de lui-meme, une boucle bloquerait jusqu'au timeout a chaque appel.
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(request_bytes)
            return s.recv(4096)

    def test_index_and_static_assets_are_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"watch2notif", body)
        self.assertEqual(self._get("/app.js")[0], 200)
        self.assertEqual(self._get("/style.css")[0], 200)

    def test_favicon_is_the_tray_icon(self):
        # Comme blink2video : /favicon.ico, garde une semaine par le navigateur.
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/favicon.ico", timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "image/x-icon")
            self.assertEqual(r.headers["Cache-Control"], "public, max-age=604800")
            self.assertEqual(r.read(), notifier.ICON_FILE.read_bytes())

    def test_icons_are_filed_like_the_other_apps(self):
        # Rangees comme celles de blink2video, lidar2map et gpxsolar :
        # assets/<app>.png de 1254 px pour l'executable, assets/<app>.ico
        # aux neuf tailles de celui de blink2video pour le reste.
        page = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="icon" href="/favicon.ico">', page)
        png = (notifier.RESOURCE_DIR / "assets" / "watch2notif.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png[16:24], (1254).to_bytes(4, "big") * 2)
        ico = notifier.ICON_FILE.read_bytes()
        self.assertEqual(notifier.ICON_FILE.name, "watch2notif.ico")
        self.assertEqual(ico[:4], b"\x00\x00\x01\x00")
        self.assertEqual(int.from_bytes(ico[4:6], "little"), 9)

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/does-not-exist")
        self.assertEqual(ctx.exception.code, 404)

    def test_refused_post_with_body_never_loses_its_response(self):
        # Repondre avant d'avoir lu le corps fermait la connexion sur des
        # octets non lus : RST sous Windows, reponse perdue (WinError 10053)
        # pour environ 4 % des requetes, mesure le 2026-09-26. Cinquante
        # envois avec un corps consequent rendent la course presque certaine.
        for _ in range(50):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post("/api/does-not-exist", {"donnees": "x" * 20000})
            self.assertEqual(ctx.exception.code, 404)

    def test_state_reflects_isolated_empty_config(self):
        status, body = self._get("/api/state")
        data = json.loads(body)
        self.assertEqual(data["config"]["feeds"], [])
        self.assertNotIn("autostart_enabled", data)       # c'est /api/autostart, celle du commun
        self.assertFalse(data["paused"])
        self.assertNotIn("update", data)

    def test_api_maj_depuis_les_sources_n_est_pas_installable(self):
        status, body = self._get("/api/maj")
        data = json.loads(body)
        self.assertFalse(data["possible"])
        self.assertEqual(data["raison"], "source_mode")
        self.assertEqual(data["etat"]["etat"], "inactif")
        self.assertIn("{version}", data["libelles"]["disponible"])

    def test_le_bandeau_commun_est_servi(self):
        status, body = self._get("/nico579-maj.js")
        self.assertEqual(status, 200)
        self.assertIn("/api/maj", body.decode("utf-8") if isinstance(body, bytes) else body)

    def test_save_config_persists_and_returns_generated_keys(self):
        status, result = self._post("/api/save-config", {
            "lang": "fr",
            "feeds": [{"key": "", "label": "Feed A", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 45}],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["feeds"][0]["key"], "feed_a")

        on_disk = json.loads(notifier.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["lang"], "fr")
        self.assertEqual(on_disk["feeds"][0]["url"], "https://a.test")

    def test_etat_annonce_version_et_pid_pour_l_en_tete(self):
        # Affiches en tete de page, comme blink2video.
        data = json.loads(self._get("/api/state")[1])
        self.assertEqual(data["version"], notifier.update_check.VERSION)
        self.assertEqual(data["pid"], os.getpid())
        page = self._get("/")[1].decode("utf-8")
        self.assertIn('id="server-version"', page)
        self.assertIn('id="server-pid"', page)
        self.assertEqual(notifier.i18n.STRINGS["header_pid"]["fr"], "PID serveur {pid}")

    def test_type_vide_ne_remplace_pas_le_type_connu(self):
        # 0.2.0 a 0.2.4 : la page renvoyait un type vide pour chaque source ;
        # chacune passait en RSS au premier enregistrement.
        self._post("/api/save-config", {"lang": "fr", "feeds": [
            {"key": "", "label": "Mes issues", "url": "nico579/watch2notif",
             "enabled": True, "kind": "github_issues", "interval_seconds": 300}]})
        status, result = self._post("/api/save-config", {"lang": "fr", "feeds": [
            {"key": "mes_issues", "label": "Mes issues", "url": "nico579/watch2notif",
             "enabled": True, "kind": "", "interval_seconds": 300},
            {"key": "", "label": "Nouvelle", "url": "https://b.test",
             "enabled": True, "kind": "", "interval_seconds": None}]})
        self.assertTrue(result["ok"])
        on_disk = json.loads(notifier.CONFIG_FILE.read_text(encoding="utf-8"))
        types = {feed["key"]: feed["kind"] for feed in on_disk["feeds"]}
        self.assertEqual(types["mes_issues"], "github_issues")
        # Une source nouvelle sans type prend toujours celui par defaut.
        self.assertEqual(types["nouvelle"], notifier.DEFAULT_KIND)

    def test_page_remplit_les_types_avant_de_les_choisir(self):
        # Garde sur l'ordre, faute de navigateur dans ces tests : une valeur
        # donnee a une liste encore vide est ignoree par le navigateur.
        source = (notifier.GUI_DIR / "app.js").read_text(encoding="utf-8")
        creation = source[source.index("function createFeedRow"):]
        creation = creation[:creation.index("\n}\n")]
        self.assertLess(creation.index("fillKindOptions(kindSelect)"),
                        creation.index("kindSelect.value = feed.kind"))

    def test_set_pause_toggles_the_real_event(self):
        self._post("/api/set-pause", {"paused": True})
        self.assertTrue(self.pause_event.is_set())
        status, body = self._get("/api/state")
        self.assertTrue(json.loads(body)["paused"])

        self._post("/api/set-pause", {"paused": False})
        self.assertFalse(self.pause_event.is_set())

    def test_l_ancienne_route_update_install_n_existe_plus(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/update-install", {})
        self.assertEqual(ctx.exception.code, 404)

    def test_maj_installer_demarre_l_installateur(self):
        installateur = self.state.installateur
        with mock.patch.object(installateur, "demarrer", return_value=True) as demarrer:
            status, result = self._post("/api/maj-installer", {})
        self.assertEqual(result, {"ok": True})
        demarrer.assert_called_once()

    def test_malformed_path_returns_400_not_a_crash(self):
        # urlparse leve ValueError sur certaines formes manifestement
        # invalides (IPv6 mal ferme, ex. "http://[abc/foo"), le meme piege
        # deja corrige pour Origin dans hote_autorise() et pour self.path
        # dans blink2video/serve.py, jamais reporte ici jusqu'a cet audit.
        # Pas "//[abc" : deja normalise en "/[abc" par le parsing HTTP de la
        # stdlib avant meme d'atteindre urlparse sur Python 3.9+ (verifie
        # empiriquement ici), ce cas precis ne se reproduit que sur le
        # Python 3.8 vise par le build Windows 7 de blink2video/lidar2map,
        # absents de watch2notif.
        reponse = self._raw_request(
            b"GET http://[abc/foo HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        self.assertIn(b"400", reponse.split(b"\r\n", 1)[0])

    def test_invalid_content_length_returns_400_not_a_crash(self):
        reponse = self._raw_request(
            b"POST /api/set-pause HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Length: not-a-number\r\nConnection: close\r\n\r\n"
        )
        self.assertIn(b"400", reponse.split(b"\r\n", 1)[0])

    def test_enregistrer_les_flux_ne_touche_pas_au_demarrage_automatique(self):
        # Le demarrage n'est plus un champ de ce formulaire : l'ancienne page l'envoyait a chaque
        # enregistrement, et son absence le desactiverait si on la lisait comme « decoche ».
        self.autostart_enabled = True
        status, result = self._post("/api/save-config", {
            "lang": "fr",
            "feeds": [{"key": "", "label": "Feed A", "url": "https://a.test", "enabled": True, "kind": "rss", "interval_seconds": 45}],
        })
        self.assertTrue(result["ok"])
        self.assertTrue(self.autostart_enabled)
        self.assertNotIn("autostart_error", result)

    def test_la_case_de_demarrage_du_commun_agit_tout_de_suite(self):
        self.assertFalse(json.loads(self._get("/api/autostart")[1])["actif"])
        status, result = self._post("/api/autostart", {"actif": True})
        self.assertEqual((result["ok"], result["actif"]), (True, True))
        self.assertTrue(self.autostart_enabled)            # simulacre, jamais le vrai systeme
        self.assertTrue(json.loads(self._get("/api/autostart")[1])["actif"])
        status, result = self._post("/api/autostart", {"actif": False})
        self.assertEqual((result["ok"], result["actif"]), (True, False))

    def test_un_echec_du_demarrage_est_dit_sans_toucher_aux_flux(self):
        with mock.patch.object(notifier.demarrage, "activer", side_effect=RuntimeError("boom")):
            status, result = self._post("/api/autostart", {"actif": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")
        self.assertFalse(result["actif"])

    def test_le_choix_de_langue_du_commun_est_garde_dans_la_config(self):
        status, result = self._post("/api/langue", {"code": "fr"})
        self.assertEqual((result["ok"], result["code"]), (True, "fr"))
        self.assertEqual(json.loads(self._get("/api/langue")[1])["code"], "fr")
        on_disk = json.loads(notifier.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["lang"], "fr")
        # Une simple detection du navigateur n'est pas un choix : rien d'ecrit.
        self._post("/api/langue", {"code": "en", "detectee": True})
        self.assertEqual(json.loads(self._get("/api/langue")[1])["code"], "fr")

    def test_history_empty_then_populated_after_a_real_notify_call(self):
        self.assertEqual(json.loads(self._get("/api/history")[1]), {"entries": []})
        with mock.patch.object(notifier.notify_backend, "notify"):
            notifier.notify("Some feed", {"title": "T", "author": "A", "summary": "", "link": "https://x.test"})
        entries = json.loads(self._get("/api/history")[1])["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["feed_label"], "Some feed")

        self._post("/api/clear-history", {})
        self.assertEqual(json.loads(self._get("/api/history")[1]), {"entries": []})


@unittest.skipUnless(notifier._tray_disponible(), "zone de notification indisponible sur cette machine")
class TrayMenuTests(unittest.TestCase):
    """Construit le vrai tray (pystray, par nico579_commons.tray) et
    inspecte son menu, sans jamais appeler icon.run() ni executer() : ils
    bloqueraient indefiniment et feraient apparaitre une vraie icone
    (regression constatee pendant la migration lidar2map)."""

    def setUp(self):
        self.pause_event = threading.Event()
        self.state = notifier.SharedState(self.pause_event)
        self.stop_event = threading.Event()
        lang_patch = mock.patch.object(notifier, "load_config", return_value={"lang": "en"})
        lang_patch.start()
        self.addCleanup(lang_patch.stop)
        self.tray = notifier._construire_tray("http://127.0.0.1:0/", self.state, self.stop_event)
        self.icon = self.tray.construire()
        if sys.platform == "win32":
            # pystray registers a native window class in __init__, but only
            # unregisters it when its message loop ends. These menu tests
            # never run that loop: release the class explicitly so Python
            # object-id reuse cannot collide with a preceding fixture.
            self.addCleanup(self.icon._unregister_class, self.icon._atom)

    def _labels(self):
        return [str(item) for item in self.icon.menu]

    def test_menu_commun_sans_mise_a_jour(self):
        # Le meme menu dans les quatre applications, sans element propre :
        # pause, historique et aide sont dans la page qu'ouvre Open.
        self.assertEqual(self._labels(), [
            "Open", "Restart", "Stop", "Create a Desktop shortcut"])

    def test_menu_en_francais(self):
        with mock.patch.object(notifier, "load_config", return_value={"lang": "fr"}):
            labels = self._labels()
        self.assertEqual(labels, ["Ouvrir", "Redémarrer", "Arrêter",
                                  "Créer un raccourci sur le Bureau"])

    def test_stop_event_est_l_arret_de_l_icone(self):
        # L'Installateur leve stop_event une fois l'assistant pret, sans
        # acces a l'icone : c'est l'arret du Tray commun qui la referme (sa
        # veille, testee dans nico579-commons). Sans ce lien, icon.run() ne
        # se debloquait jamais apres une mise a jour installee.
        self.assertIs(self.tray.arret, self.stop_event)

    def test_mise_a_jour_affichee_quand_une_version_est_connue(self):
        with mock.patch.object(notifier, "VERIFICATEUR", FauxVerificateur("9.9.9")):
            self.assertIn("Update to 9.9.9", self._labels())

    def test_ouvrir_ouvre_la_page(self):
        # MenuItem est appelable (__call__(icon) -> action(icon, item)) :
        # c'est ainsi qu'un clic reel invoque le callback.
        ouvrir = next(item for item in self.icon.menu if str(item) == "Open")
        self.assertTrue(ouvrir.default)
        with mock.patch.object(notifier.webbrowser, "open") as navigateur:
            ouvrir(self.icon)
        navigateur.assert_called_once_with("http://127.0.0.1:0/")


class VerificationDeVersionTests(unittest.TestCase):
    def test_la_derniere_reponse_est_gardee_dans_le_dossier_de_donnees(self):
        self.assertEqual(notifier.VERIFICATEUR._cache, notifier.data_paths.DATA_DIR / "maj.json")
        self.assertEqual(notifier.VERIFICATEUR.fraicheur_s, 3600)


class BoutonReglagesTests(unittest.TestCase):
    """Le bouton « Reglages » commun et les fichiers JavaScript communs de la page."""

    def test_la_page_place_le_bouton_avant_le_choix_de_langue(self):
        html = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/nico579-reglages.js"></script>', html)
        self.assertLess(html.index("/app.js"), html.index("/nico579-reglages.js"))
        # Meme place que dans blink2video : juste avant FR / EN.
        self.assertLess(html.index('id="nico579-reglages"'), html.index('id="lang-toggle"'))

    def test_reglages_generaux_vont_dans_le_panneau_commun(self):
        # Pause et demarrage automatique ne sont plus dans l'onglet : la pause est ajoutee au
        # panneau Reglages par app.js, le demarrage est la case du commun.
        html = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("autostart-check", html)
        self.assertNotIn("pause-check", html)
        js = (notifier.GUI_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("nico579Reglages.ajouter", js)
        self.assertNotIn("autostart_enabled", js)

    def test_le_selecteur_de_langue_est_celui_du_commun(self):
        html = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="lang-toggle" data-nico579-langue', html)
        self.assertNotIn('data-lang="fr"', html)             # les boutons sont dessines par le commun
        self.assertLess(html.index("/app.js"), html.index("/nico579-langue.js"))
        js = (notifier.GUI_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("'nico579-langue'", js)
        self.assertNotIn("getElementById('lang-toggle')", js)

    def test_l_onglet_des_sources_s_appelle_flux(self):
        html = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-i18n="tab_feeds"', html)
        self.assertNotIn("tab_settings", html)
        self.assertEqual(notifier.i18n.STRINGS["tab_feeds"], {"en": "Feeds", "fr": "Flux"})

    def test_l_executable_embarque_les_fichiers_communs(self):
        # PyInstaller n'embarque les donnees d'un paquet que si le .spec le demande ;
        # sans cela la page reclame /nico579-maj.js et /nico579-reglages.js en 404.
        spec = (Path(notifier.__file__).parent / "watch2notif.spec").read_text(encoding="utf-8")
        self.assertIn('collect_data_files("nico579_commons")', spec)
        self.assertIn("COMMUN_DATAS", spec.split("datas=", 1)[1])

    def test_les_fichiers_communs_sont_dans_le_paquet(self):
        self.assertEqual(notifier.serveweb.fichiers_manquants(), [])


class SortieStandardTests(unittest.TestCase):
    """Ou vont les print() : au journal, des qu'on ne peut pas compter sur la sortie standard."""

    def test_executable_fige_toujours_au_journal(self):
        flux = object()
        self.assertTrue(notifier.doit_journaliser(None, False, False))     # lance par le raccourci
        self.assertTrue(notifier.doit_journaliser(flux, True, False))      # relance : tube sans lecteur
        self.assertTrue(notifier.doit_journaliser(None, True, False))

    def test_depuis_les_sources_on_garde_la_console(self):
        self.assertFalse(notifier.doit_journaliser(object(), False, False))

    def test_l_auto_test_garde_sa_sortie_standard_que_la_ci_lit(self):
        for stdout, fige in ((object(), True), (object(), False), (None, True)):
            with self.subTest(stdout=stdout, fige=fige):
                self.assertFalse(notifier.doit_journaliser(stdout, fige, True))


class TrayActionsTests(unittest.TestCase):
    """Les actions que watch2notif donne au menu commun, appelees
    directement : ni icone, ni vraie relance, ni vrai raccourci sur le
    Bureau (voir memoire feedback-tests-bureau-reel)."""

    URL = "http://127.0.0.1:0/"

    def setUp(self):
        self.state = notifier.SharedState(threading.Event())
        self.stop_event = threading.Event()
        self.journal = []
        self.actions = notifier._actions_tray(
            self.URL, self.state, self.stop_event,
            lambda: self.journal.append("serveur arrete"))

    def test_redemarrer_libere_port_et_verrou_puis_relance(self):
        def relancer(commande, **options):
            self.journal.append(("relance", commande, options))
            return "processus"

        with mock.patch.object(notifier.single_instance, "release",
                               side_effect=lambda: self.journal.append("verrou libere")), \
                mock.patch.object(notifier.relance, "relancer", side_effect=relancer):
            self.actions.redemarrer()
        self.assertEqual(self.journal[:2], ["serveur arrete", "verrou libere"])
        _, commande, options = self.journal[2]
        self.assertEqual(commande, notifier.autostart_manager.notifier_command())
        self.assertEqual(options["nom"], "watch2notif")

    def test_redemarrer_donne_au_nouveau_process_une_sortie_qui_survit_a_celui_ci(self):
        # Sans stdout ni stderr, un process sans console (l'executable) les remplace par
        # un tube que le nouveau process perd des que celui-ci sort : le premier print()
        # de ce dernier leve « OSError: [Errno 22] Invalid argument » (2026-10-07).
        with mock.patch.object(notifier.single_instance, "release"),                 mock.patch.object(notifier.relance, "relancer") as relancer:
            self.actions.redemarrer()
        options = relancer.call_args.kwargs
        self.assertIs(options["stdout"], notifier.subprocess.DEVNULL)
        self.assertIs(options["stderr"], notifier.subprocess.DEVNULL)

    def test_arreter_arrete_le_serveur(self):
        self.actions.arreter()
        self.assertEqual(self.journal, ["serveur arrete"])

    def test_version_disponible(self):
        with mock.patch.object(notifier, "VERIFICATEUR", FauxVerificateur(None)):
            self.assertIsNone(self.actions.version_disponible())
        with mock.patch.object(notifier, "VERIFICATEUR", FauxVerificateur("9.9.9")):
            self.assertEqual(self.actions.version_disponible(), "9.9.9")

    def test_mettre_a_jour_installe_quand_c_est_possible(self):
        self.assertFalse(self.actions.mettre_a_jour_referme)
        self.state.installateur = FauxInstallateur(possible=True)
        with mock.patch.object(notifier.webbrowser, "open") as ouvrir:
            self.actions.mettre_a_jour()
        self.assertEqual(self.state.installateur.demarre, 1)
        ouvrir.assert_not_called()

    def test_mettre_a_jour_ouvre_la_page_sinon(self):
        # Installation impossible ici (sources...), telechargement deja en
        # cours, ou pas d'installateur : la page dit ou en est la mise a jour.
        cas = ((FauxInstallateur(possible=False), "impossible"),
               (FauxInstallateur(possible=True, accepte=False), "deja en cours"),
               (None, "aucun installateur"))
        for installateur, nom in cas:
            with self.subTest(cas=nom):
                self.state.installateur = installateur
                with mock.patch.object(notifier.webbrowser, "open") as ouvrir:
                    self.actions.mettre_a_jour()
                ouvrir.assert_called_once_with(self.URL)

    def test_aide_dans_la_page_plus_dans_le_menu(self):
        # L'aide a quitte le menu pour l'en-tete de la page, comme le bouton
        # Aide de lidar2map et gpxsolar.
        page = (notifier.GUI_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="https://github.com/nico579/watch2notif#readme"', page)
        self.assertIn('data-i18n="help_link"', page)
        self.assertEqual(notifier.i18n.t("help_link", "fr"), "Aide (GitHub)")

    def test_creer_raccourci_ouvre_les_reglages(self):
        with mock.patch.object(notifier.raccourci, "creer", return_value=0) as creer:
            self.actions.creer_raccourci()
        args, kwargs = creer.call_args
        self.assertEqual(args[0], "watch2notif")
        self.assertEqual(args[1], notifier.autostart_manager.notifier_command() + ["--settings"])
        self.assertEqual(kwargs["icone"], notifier.ICON_FILE)


if __name__ == "__main__":
    unittest.main()
