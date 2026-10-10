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
        self.assertEqual(corps["model"], "claude-haiku-5-5")
        # Haiku 5.5 reflechit par defaut : effort bas, et de la place pour la reflexion.
        self.assertEqual(corps["output_config"], {"effort": "low"})
        self.assertGreaterEqual(corps["max_tokens"], 1024)
        # Refuses (400) par Haiku 5.5 : budget de reflexion, echantillonnage, prefill.
        for champ in ("thinking", "temperature", "top_p", "top_k"):
            self.assertNotIn(champ, corps)
        self.assertEqual(corps["messages"][-1]["role"], "user")
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

    @staticmethod
    def api_brute(donnees):
        return lambda requete, timeout=None: ReponseSimulee(donnees)

    def test_les_blocs_de_reflexion_avant_le_texte_sont_ignores(self):
        # La reponse de Haiku 5.5 peut commencer par un bloc "thinking" au texte vide.
        donnees = {"stop_reason": "end_turn", "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": '{"pertinent": true, "raison": "question sur le stockage"}'}]}
        verdict = filtre_ia.juger("x", Entree(), cle="k", ouvrir=self.api_brute(donnees))
        self.assertTrue(verdict.pertinent)
        self.assertEqual(verdict.raison, "question sur le stockage")

    def test_un_refus_du_modele_est_dit(self):
        donnees = {"stop_reason": "refusal", "stop_details": {"type": "refusal", "category": "cyber"},
                   "content": []}
        with self.assertRaises(filtre_ia.FiltreIndisponible) as ctx:
            filtre_ia.juger("x", Entree(), cle="k", ouvrir=self.api_brute(donnees))
        self.assertIn("refuse", str(ctx.exception))
        self.assertIn("cyber", str(ctx.exception))

    def test_une_reponse_coupee_par_max_tokens_est_dite(self):
        donnees = {"stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "", "signature": "s"}]}
        with self.assertRaises(filtre_ia.FiltreIndisponible) as ctx:
            filtre_ia.juger("x", Entree(), cle="k", ouvrir=self.api_brute(donnees))
        self.assertIn("max_tokens", str(ctx.exception))


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

    def test_une_panne_n_est_essayee_qu_une_fois_par_cycle(self):
        # Reseau coupe : chaque appel couterait DELAI_S. La premiere panne suffit,
        # les entrees suivantes sont notifiees avec la meme raison sans rappeler l'API.
        def juger(consigne, entree):
            raise filtre_ia.FiltreIndisponible("delai depasse")

        entrees = [Entree(f"e{i}", timestamp=self.now - 10 - i) for i in range(3)]
        envoi, filtre = self.poll(entrees, juger)
        self.assertEqual(filtre.call_count, 1)
        self.assertEqual(len(envoi.call_args_list), 3)
        for appel in envoi.call_args_list:
            self.assertIn("delai depasse", appel.args[2])

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

    def test_seul_un_lien_http_est_confie_au_clic(self):
        # Le lien vient tel quel du flux ; le clic le donne au systeme.
        for lien, attendu in (("https://example.test/a", "https://example.test/a"),
                              ("HTTP://example.test/b", "HTTP://example.test/b"),
                              ("file:///C:/Windows/System32/calc.exe", ""),
                              ("ms-settings:", ""), ("javascript:alert(1)", ""), ("", "")):
            with self.subTest(lien=lien), \
                    mock.patch.object(notifier.notify_backend, "notify") as backend, \
                    mock.patch.object(notifier.notification_history, "append") as historique:
                entree = Entree()
                entree._data["link"] = lien
                notifier.notify("Flux", entree)
            self.assertEqual(backend.call_args.kwargs["url"], attendu)
            self.assertEqual(historique.call_args.args[4], lien)   # l'historique garde l'original

    def test_l_intervalle_est_borne(self):
        lignes = [{"label": str(valeur), "url": "https://example.test/feed", "kind": "rss",
                   "interval_seconds": valeur} for valeur in (-60, 1, 5, 600, 10**9)]
        intervalles = [flux["interval_seconds"] for flux in notifier.build_feeds_from_rows(lignes)]
        self.assertEqual(intervalles, [5, 5, 5, 600, 7 * 24 * 3600])


class CleAbsenteSignalee(unittest.TestCase):
    """Sans ANTHROPIC_API_KEY, la page le dit sous chaque consigne ; l'etat ne donne
    qu'un booleen, jamais la cle."""

    def etat(self, env):
        routes, _ = notifier.build_api_routes(mock.Mock(is_set=lambda: False), mock.Mock(), mock.Mock())
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch.object(notifier, "load_config", return_value={"feeds": [], "lang": "fr"}):
            return routes["state"]()

    def test_l_etat_dit_si_la_cle_est_la_sans_la_donner(self):
        with mock.patch.object(notifier, "_installateur", return_value=mock.Mock()):
            absente = self.etat({})
            presente = self.etat({"ANTHROPIC_API_KEY": "sk-ant-secret"})
        self.assertIs(absente["cle_ia_presente"], False)
        self.assertIs(presente["cle_ia_presente"], True)
        self.assertNotIn("sk-ant-secret", json.dumps(presente))

    def test_la_page_affiche_l_avertissement_seulement_sans_cle(self):
        js = (notifier.GUI_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("cleIaPresente = state.cle_ia_presente !== false;", js)
        self.assertIn("if (!cleIaPresente) {", js)
        self.assertIn("'filter_key_missing'", js)
        for cle in ("filter_key_missing", "filter_key_url"):
            self.assertEqual(set(notifier.i18n.STRINGS[cle]), {"en", "fr"}, cle)
        self.assertTrue(notifier.i18n.STRINGS["filter_key_url"]["en"].endswith("#ai-filter-optional"))
        readme = (notifier.GUI_DIR.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("## AI filter (optional)", readme)            # l'ancre du lien existe
        readme_fr = (notifier.GUI_DIR.parent / "README.fr.md").read_text(encoding="utf-8")
        self.assertIn("## Filtre IA (facultatif)", readme_fr)


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
