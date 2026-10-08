"""Filtre IA facultatif d'une source (filtre_ia.py) et son branchement dans poll_feed.

Aucun appel reseau : la reponse de l'API Anthropic est simulee. Le tri reel sur de
vrais messages se verifie a la main, une fois la cle ANTHROPIC_API_KEY posee.
"""
import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import filtre_ia
import notifier


class Entree:
    def __init__(self, entry_id="e1", title="Issue with local storage", summary="", timestamp=None):
        self.id = entry_id
        self._data = {"title": title, "author": "u/quelquun", "link": f"https://example.test/{entry_id}",
                      "summary": summary}
        if timestamp is not None:
            self._data["updated_parsed"] = time.gmtime(timestamp)

    def get(self, key, default=None):
        return self._data.get(key, default)


class ReponseSimulee:
    def __init__(self, donnees):
        self._corps = json.dumps(donnees).encode("utf-8")

    def read(self):
        return self._corps

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def api_qui_repond(texte, requetes=None):
    def ouvrir(requete, timeout=None):
        if requetes is not None:
            requetes.append(requete)
        return ReponseSimulee({"content": [{"type": "text", "text": texte}]})
    return ouvrir


class Juger(unittest.TestCase):
    def test_un_verdict_pertinent_avec_sa_raison(self):
        requetes = []
        verdict = filtre_ia.juger(
            "Questions auxquelles blink2video repond.", Entree(summary="<p>My USB clips vanish</p>"),
            cle="sk-test", ouvrir=api_qui_repond('{"pertinent": true, "raison": "veut garder ses clips USB"}', requetes))
        self.assertTrue(verdict.pertinent)
        self.assertEqual(verdict.raison, "veut garder ses clips USB")
        requete = requetes[0]
        self.assertEqual(requete.full_url, filtre_ia.URL)
        self.assertEqual(requete.get_header("X-api-key"), "sk-test")
        self.assertEqual(requete.get_header("Anthropic-version"), filtre_ia.VERSION_API)
        corps = json.loads(requete.data.decode("utf-8"))
        self.assertEqual(corps["model"], filtre_ia.MODELE)
        message = corps["messages"][0]["content"]
        self.assertIn("Questions auxquelles blink2video repond.", message)
        self.assertIn("My USB clips vanish", message)
        self.assertNotIn("<p>", message)                     # le HTML du flux est retire

    def test_un_verdict_negatif(self):
        verdict = filtre_ia.juger("x", Entree(), cle="k",
                                  ouvrir=api_qui_repond('Voici : {"pertinent": false, "raison": "facturation"}'))
        self.assertFalse(verdict.pertinent)

    def test_sans_cle_pas_de_verdict(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(filtre_ia.FiltreIndisponible) as ctx:
                filtre_ia.juger("x", Entree())
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_la_cle_vient_de_l_environnement(self):
        requetes = []
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": " sk-env "}):
            filtre_ia.juger("x", Entree(), ouvrir=api_qui_repond('{"pertinent": true, "raison": ""}', requetes))
        self.assertEqual(requetes[0].get_header("X-api-key"), "sk-env")

    def test_une_erreur_de_l_api_est_dite(self):
        def ouvrir(requete, timeout=None):
            raise urllib.error.HTTPError(filtre_ia.URL, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error": {"message": "credit balance is too low"}}'))
        with self.assertRaises(filtre_ia.FiltreIndisponible) as ctx:
            filtre_ia.juger("x", Entree(), cle="k", ouvrir=ouvrir)
        self.assertIn("400", str(ctx.exception))
        self.assertIn("credit balance", str(ctx.exception))

    def test_reseau_coupe(self):
        def ouvrir(requete, timeout=None):
            raise urllib.error.URLError("pas de reseau")
        with self.assertRaises(filtre_ia.FiltreIndisponible):
            filtre_ia.juger("x", Entree(), cle="k", ouvrir=ouvrir)

    def test_reponse_illisible(self):
        for texte in ("oui", '{"raison": "sans verdict"}', '{"pertinent": "yes"}', "{pas du json}"):
            with self.assertRaises(filtre_ia.FiltreIndisponible, msg=texte):
                filtre_ia.juger("x", Entree(), cle="k", ouvrir=api_qui_repond(texte))


class BranchementDansLaBoucle(unittest.TestCase):
    """poll_feed : une entree ecartee est marquee vue sans notification ; une entree
    retenue est notifiee avec la raison ; sans verdict, on notifie quand meme."""

    def setUp(self):
        self.temporaire = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporaire.cleanup)
        self.racine = Path(self.temporaire.name)
        patch = mock.patch.object(notifier, "STATE_DIR", self.racine)
        patch.start()
        self.addCleanup(patch.stop)
        self.now = int(time.time())
        self.feed = {"key": "reddit", "label": "Reddit", "filtre_ia": "Questions sur le stockage local."}
        (self.racine / "reddit.json").write_text(json.dumps(
            {"version": 2, "seen_ids": ["ancien"], "pending_ids": [], "newest_timestamp": self.now - 20_000}),
            encoding="utf-8")

    def poll(self, entrees, juger):
        with mock.patch.object(notifier, "fetch_entries", return_value=entrees), \
                mock.patch.object(notifier.filtre_ia, "juger", side_effect=juger) as filtre, \
                mock.patch.object(notifier, "notify") as envoi:
            notifier.poll_feed(self.feed)
        return envoi, filtre

    def etat(self):
        return json.loads((self.racine / "reddit.json").read_text(encoding="utf-8"))

    def test_ecartee_sans_notification_mais_vue(self):
        def juger(consigne, entree):
            self.assertEqual(consigne, "Questions sur le stockage local.")
            return filtre_ia.Verdict(entree.id == "utile", "raison " + entree.id)

        envoi, _ = self.poll([Entree("utile", timestamp=self.now - 10),
                              Entree("bruit", timestamp=self.now - 20)], juger)
        self.assertEqual([(c.args[1].id, c.args[2]) for c in envoi.call_args_list], [("utile", "raison utile")])
        etat = self.etat()
        self.assertIn("bruit", etat["seen_ids"])               # pas re-jugee au prochain cycle
        self.assertIn("utile", etat["seen_ids"])
        self.assertEqual(etat["pending_ids"], [])

    def test_sans_verdict_on_notifie_en_le_disant(self):
        def juger(consigne, entree):
            raise filtre_ia.FiltreIndisponible("variable ANTHROPIC_API_KEY absente")

        envoi, _ = self.poll([Entree("e", timestamp=self.now - 10)], juger)
        self.assertEqual(len(envoi.call_args_list), 1)
        self.assertIn("filtre IA indisponible", envoi.call_args.args[2])
        self.assertIn("ANTHROPIC_API_KEY", envoi.call_args.args[2])

    def test_sans_consigne_le_filtre_n_est_pas_appele(self):
        self.feed["filtre_ia"] = "  "
        envoi, filtre = self.poll([Entree("e", timestamp=self.now - 10)], lambda *a: None)
        filtre.assert_not_called()
        self.assertEqual(envoi.call_args.args, ("Reddit", envoi.call_args.args[1]))   # sans raison


class ConfigurationEtNotification(unittest.TestCase):
    def test_la_consigne_est_gardee_avec_la_source(self):
        flux = notifier.build_feeds_from_rows([
            {"label": "Reddit", "url": "https://www.reddit.com/r/x/search.rss?q=y", "enabled": True,
             "kind": "rss", "interval_seconds": 3600, "filtre_ia": "  Seulement les questions.  "},
            {"label": "Autre", "url": "https://example.test/feed", "enabled": True, "kind": "rss"},
        ])
        self.assertEqual(flux[0]["filtre_ia"], "Seulement les questions.")
        self.assertEqual(flux[1]["filtre_ia"], "")

    def test_changer_la_consigne_ne_reamorce_pas_la_source(self):
        # L'empreinte (type + adresse) decide d'un re-amorcage : une consigne modifiee ne
        # doit pas faire oublier ce qui a deja ete vu.
        a = {"kind": "rss", "url": "https://example.test/feed", "filtre_ia": "a"}
        b = dict(a, filtre_ia="b")
        self.assertEqual(notifier._feed_fingerprint(a), notifier._feed_fingerprint(b))

    def test_la_raison_ouvre_le_texte_de_la_notification(self):
        with mock.patch.object(notifier.notify_backend, "notify") as backend, \
                mock.patch.object(notifier.notification_history, "append"):
            notifier.notify("Reddit", Entree(summary="Bonjour"), "veut garder ses clips")
        self.assertIn("veut garder ses clips | Bonjour", backend.call_args.kwargs["message"])


class Page(unittest.TestCase):
    def test_la_page_ecrit_et_relit_la_consigne(self):
        js = (notifier.GUI_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("filtre_ia: tr.filterInput.value.trim()", js)
        self.assertIn("feed-filter-row", js)
        # Les deux selecteurs de lignes ignorent la ligne de consigne : sinon les clefs
        # renvoyees par le serveur seraient reaffectees a la mauvaise source.
        self.assertEqual(js.count("'#feeds-body tr.feed-row'"), 2)
        self.assertNotIn("'#feeds-body tr'", js)

    def test_textes_dans_les_deux_langues(self):
        for cle in ("filter_button", "filter_button_title", "filter_placeholder"):
            self.assertEqual(set(notifier.i18n.STRINGS[cle]), {"en", "fr"}, cle)


if __name__ == "__main__":
    unittest.main()
