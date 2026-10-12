"""La page de watch2notif dans un vrai navigateur.

test_pairing_ui.cjs exécute le script de jumelage sous Node avec un DOM
factice, et test_notifier_web_tray.py interroge les routes en HTTP ; aucun ne
voit la page entière. Ici, les vraies routes (build_api_routes) sont servies
par le vrai serveweb sur un port éphémère, avec des données jetables et le
démarrage automatique simulé, exactement comme dans test_notifier_web_tray.py,
et Playwright (bibliothèque de Microsoft qui pilote un vrai Chromium) charge la
page : aucune erreur JavaScript ni réponse en échec, bascule FR / EN, onglets,
ajout d'un flux et enregistrement, panneau Réglages commun avec sa case de
démarrage automatique.

Jumeau des tests de page de gpxsolar, lidar2map et blink2video. Sans
Playwright, le test est sauté ; la CI l'installe (job « navigateur »).

    python -m pip install playwright
    python -m playwright install chromium
    python -m unittest tests.test_page_navigateur -v
"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import notifier  # noqa: E402
import update_check  # noqa: E402

try:
    from playwright.sync_api import Error as ErreurPlaywright, expect, sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright absent")
class PageWatch2notif(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.navigateur = cls.playwright.chromium.launch(headless=True)
        except ErreurPlaywright as erreur:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chromium absent : {erreur}")

    @classmethod
    def tearDownClass(cls):
        cls.navigateur.close()
        cls.playwright.stop()

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        donnees = Path(self.dossier.name) / "data"
        donnees.mkdir()
        self.correctifs = [
            mock.patch.object(notifier.data_paths, "DATA_DIR", donnees),
            mock.patch.object(notifier, "CONFIG_FILE", donnees / "config.json"),
            mock.patch.object(notifier, "STATE_DIR", donnees / "state"),
            mock.patch.object(notifier.notification_history, "HISTORY_FILE",
                              donnees / "notification_history.json"),
        ]
        self.demarrage_actif = False

        def activer(_entree):
            self.demarrage_actif = True
            return []

        def desactiver(_entree):
            self.demarrage_actif = False

        # Jamais le vrai dossier Démarrage, systemd ou launchd : les trois gestes
        # de nico579_commons.demarrage sont simulés, comme dans test_notifier_web_tray.py.
        self.correctifs.append(mock.patch.multiple(
            notifier.demarrage, est_actif=lambda _entree: self.demarrage_actif,
            activer=activer, desactiver=desactiver))
        for correctif in self.correctifs:
            correctif.start()
        notifier.save_config(notifier.default_config())
        pause, arret = threading.Event(), threading.Event()
        api, post = notifier.build_api_routes(pause, notifier.SharedState(pause), arret)
        self.serveur = notifier.serveweb.demarrer(
            bind="127.0.0.1", port=0, trusted_host="", gui_dir=notifier.GUI_DIR,
            api_routes=api, post_routes=post, favicon=notifier.ICON_FILE)
        self.adresse = f"http://127.0.0.1:{self.serveur.server_address[1]}/"
        self.contexte = self.navigateur.new_context(locale="fr-FR", viewport={"width": 1280, "height": 800})
        self.page = self.contexte.new_page()
        self.erreurs = []
        self.page.on("pageerror", lambda erreur: self.erreurs.append(str(erreur)))
        self.page.on("console", lambda message: self.erreurs.append(message.text)
                     if message.type == "error" else None)
        self.page.on("response", lambda r: self.erreurs.append(f"HTTP {r.status} {r.url}")
                     if r.status >= 400 else None)
        self.page.goto(self.adresse)
        expect(self.page.locator("#add-feed-btn")).not_to_be_empty()

    def tearDown(self):
        self.contexte.close()
        self.serveur.shutdown()
        self.serveur.server_close()
        for correctif in reversed(self.correctifs):
            correctif.stop()
        self.dossier.cleanup()
        self.assertEqual(self.erreurs, [])

    def test_la_page_se_charge_et_change_de_langue(self):
        bouton = self.page.locator("#add-feed-btn")
        francais = bouton.inner_text()
        self.page.get_by_role("button", name="EN", exact=True).click()
        expect(self.page.locator("html")).to_have_attribute("lang", "en")
        expect(bouton).not_to_have_text(francais)
        expect(self.page.locator("#nico579-reglages-bouton")).to_have_text("⚙ Settings…")
        self.page.get_by_role("button", name="FR", exact=True).click()
        expect(bouton).to_have_text(francais)

    def test_les_onglets_flux_et_historique(self):
        self.page.locator('.tab-btn[data-tab="history"]').click()
        expect(self.page.locator("#tab-history")).to_be_visible()
        expect(self.page.locator("#tab-settings")).to_be_hidden()
        self.page.locator('.tab-btn[data-tab="settings"]').click()
        expect(self.page.locator("#tab-settings")).to_be_visible()

    def test_ajouter_un_flux(self):
        # La configuration arrive après le chargement et redessine les lignes :
        # on compte une fois qu'elle est là.
        self.page.wait_for_load_state("networkidle")
        lignes = self.page.locator("#feeds-body tr.feed-row")
        avant = lignes.count()
        self.page.locator("#add-feed-btn").click()
        expect(lignes).to_have_count(avant + 1)

    def test_enregistrer_la_configuration(self):
        self.page.locator("#save-btn").click()
        expect(self.page.locator("#save-status")).not_to_be_empty()

    def test_le_panneau_reglages_et_le_demarrage_automatique(self):
        self.page.locator("#nico579-reglages-bouton").click()
        panneau = self.page.get_by_role("dialog", name="Réglages")
        expect(panneau).to_contain_text(f"Version {update_check.VERSION}")
        case = panneau.get_by_role("checkbox", name="Démarrer automatiquement avec le système")
        expect(case).not_to_be_checked()
        case.check()
        expect(case).to_be_checked()
        self.assertTrue(self.demarrage_actif)


if __name__ == "__main__":
    unittest.main()
