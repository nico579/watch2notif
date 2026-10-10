"""tools/rattrapage_flux.py (rattrapage ponctuel par le filtre IA) et le statut HTTP de providers/rss.py.
Aucun appel reseau : les pages et les verdicts sont simules."""
import importlib.util
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import filtre_ia
from providers import rss

CHEMIN = Path(__file__).resolve().parents[1] / "tools" / "rattrapage_flux.py"
SPEC = importlib.util.spec_from_file_location("rattrapage_flux", CHEMIN)
rattrapage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rattrapage)

MAINTENANT = time.time()
JOUR = 86400


class Entree:
    def __init__(self, nom, age_jours, titre=None, lien=None):
        self.id = f"https://www.reddit.com/r/blinkcameras/{nom}"
        self._donnees = {"title": titre or f"titre {nom}", "author": "u/x", "summary": "texte",
                         "link": lien or f"https://www.reddit.com/{nom}",
                         "updated_parsed": time.gmtime(MAINTENANT - age_jours * JOUR)}

    def get(self, cle, defaut=None):
        return self._donnees.get(cle, defaut)


class Pages(unittest.TestCase):
    URL = "https://www.reddit.com/r/blinkcameras/search.rss?q=usb+OR+download&restrict_sr=on&sort=new"

    def test_url_de_page(self):
        premiere = rattrapage.url_page(self.URL)
        self.assertIn("limit=100", premiere)
        self.assertIn("q=usb+OR+download", premiere)
        self.assertNotIn("after=", premiere)
        suivante = rattrapage.url_page(premiere, "t3_abc")
        self.assertEqual(suivante.count("limit="), 1)         # pas de limit ni after en double
        self.assertIn("after=t3_abc", suivante)

    def test_nom_complet(self):
        self.assertEqual(rattrapage.nom_complet(Entree("t3_xyz", 1)), "t3_xyz")

    def test_une_page_suffit_quand_elle_depasse_la_periode(self):
        pages = [[Entree("t3_a", 5), Entree("t3_b", 120)]]
        lire = mock.Mock(side_effect=lambda url: pages.pop(0))
        entrees = rattrapage.recuperer(self.URL, MAINTENANT - 90 * JOUR, 3, lire=lire, pause=lambda s: None)
        self.assertEqual(lire.call_count, 1)
        self.assertEqual(len(entrees), 2)

    def test_pagination_avec_after_jusqu_a_la_periode(self):
        urls = []
        pages = [[Entree("t3_a", 5), Entree("t3_b", 40)], [Entree("t3_c", 70), Entree("t3_d", 100)],
                 [Entree("t3_e", 200)]]

        def lire(url):
            urls.append(url)
            return pages.pop(0)

        pauses = []
        entrees = rattrapage.recuperer(self.URL, MAINTENANT - 90 * JOUR, 5, lire=lire, pause=pauses.append)
        self.assertEqual(len(urls), 2)                         # la page 2 contient une entree hors periode
        self.assertIn("after=t3_b", urls[1])
        self.assertEqual(len(entrees), 4)
        self.assertEqual(pauses, [rattrapage.PAUSE_ENTRE_PAGES_S])   # une pause, entre les deux pages

    def test_une_page_repetee_arrete_la_lecture(self):
        page = [Entree("t3_a", 5), Entree("t3_b", 6)]
        lire = mock.Mock(side_effect=lambda url: list(page))
        entrees = rattrapage.recuperer(self.URL, MAINTENANT - 90 * JOUR, 5, lire=lire, pause=lambda s: None)
        self.assertEqual(lire.call_count, 2)                   # la 2e page n'apporte rien
        self.assertEqual(len(entrees), 2)

    def test_une_erreur_apres_la_premiere_page_garde_les_entrees_lues(self):
        reponses = [[Entree("t3_a", 5)], RuntimeError("HTTP 429")]

        def lire(url):
            reponse = reponses.pop(0)
            if isinstance(reponse, Exception):
                raise reponse
            return reponse

        entrees = rattrapage.recuperer(self.URL, MAINTENANT - 90 * JOUR, 3, lire=lire, pause=lambda s: None)
        self.assertEqual(len(entrees), 1)

    def test_une_erreur_a_la_premiere_page_remonte(self):
        with self.assertRaises(RuntimeError):
            rattrapage.recuperer(self.URL, 0, 3, lire=mock.Mock(side_effect=RuntimeError("HTTP 429")), pause=lambda s: None)


class Periode(unittest.TestCase):
    def test_garde_la_periode_du_plus_recent_au_plus_ancien(self):
        entrees = [Entree("t3_vieux", 100), Entree("t3_milieu", 40), Entree("t3_neuf", 2)]
        gardees = rattrapage.dans_la_periode(entrees, MAINTENANT - 90 * JOUR)
        self.assertEqual([rattrapage.nom_complet(e) for e in gardees], ["t3_neuf", "t3_milieu"])

    def test_une_entree_sans_date_est_gardee(self):
        sans_date = Entree("t3_sans", 1)
        del sans_date._donnees["updated_parsed"]
        self.assertEqual(len(rattrapage.dans_la_periode([sans_date], MAINTENANT)), 1)


class Jugement(unittest.TestCase):
    def test_la_premiere_panne_arrete_les_appels(self):
        appels = []

        def juger(consigne, entree):
            appels.append(entree.id)
            raise filtre_ia.FiltreIndisponible("delai depasse")

        entrees = [Entree(f"t3_{i}", i) for i in range(4)]
        resultats = rattrapage.juger_tout(entrees, "consigne", juger=juger, afficher=lambda *a: None)
        self.assertEqual(len(appels), 1)
        self.assertEqual([r[1] for r in resultats], [None] * 4)
        self.assertEqual({r[2] for r in resultats}, {"delai depasse"})

    def test_verdicts(self):
        def juger(consigne, entree):
            return filtre_ia.Verdict(entree.id.endswith("pertinent"), "raison " + entree.id[-3:])

        resultats = rattrapage.juger_tout([Entree("t3_pertinent", 1), Entree("t3_bruit", 2)], "c",
                                          juger=juger, afficher=lambda *a: None)
        self.assertEqual([r[1].pertinent for r in resultats], [True, False])


class Rapport(unittest.TestCase):
    def test_sections_et_deja_notifie(self):
        retenu, ecarte, non_juge = Entree("t3_r", 3, "Un | titre [pipe]"), Entree("t3_e", 4), Entree("t3_n", 5)
        resultats = [(retenu, filtre_ia.Verdict(True, "veut garder ses clips"), ""),
                     (ecarte, filtre_ia.Verdict(False, "facturation"), ""),
                     (non_juge, None, "delai depasse")]
        texte = rattrapage.rapport({"key": "k", "label": "r/blink", "filtre_ia": "Les questions"}, resultats, 90,
                                   {retenu.get("link")}, maintenant=datetime(2026, 10, 10, 12, 0).astimezone())
        self.assertIn("## Retenus (1)", texte)
        self.assertIn("## Écartés (1)", texte)
        self.assertIn("## Non jugés (1)", texte)
        self.assertIn("1 retenus, 1 écartés, 1 non jugés", texte)
        self.assertIn("veut garder ses clips", texte)
        self.assertIn("| oui |", texte)                        # le retenu etait deja dans l'historique
        self.assertIn("Un / titre (pipe)", texte)               # ni | ni [] ne cassent le tableau Markdown
        self.assertIn("delai depasse", texte)
        self.assertNotIn("—", texte)                            # pas de tiret long

    def test_sans_retenu(self):
        texte = rattrapage.rapport({"key": "k", "filtre_ia": "c"}, [], 30, set())
        self.assertIn("Aucun.", texte)


class StatutHttp(unittest.TestCase):
    """Un 429 ou un 503 n'est pas un flux vide : sinon une source nouvelle est amorcee a vide."""

    def parse(self, **champs):
        retour = mock.MagicMock()
        retour.get.side_effect = lambda cle, defaut=None: champs.get(cle, defaut)
        retour.bozo = champs.get("bozo", False)
        retour.entries = champs.get("entries", [])
        retour.bozo_exception = champs.get("bozo_exception")
        return retour

    def test_erreur_http_leve(self):
        for statut in (429, 500, 503, 404):
            with self.subTest(statut=statut), mock.patch.object(rss.feedparser, "parse",
                                                               return_value=self.parse(status=statut)):
                with self.assertRaises(RuntimeError) as contexte:
                    rss.fetch_entries("https://example.test/feed")
                self.assertIn(str(statut), str(contexte.exception))

    def test_succes_et_redirection_passent(self):
        for statut in (200, 301, 302, None):
            with self.subTest(statut=statut):
                entrees = [object()]
                with mock.patch.object(rss.feedparser, "parse", return_value=self.parse(status=statut, entries=entrees)):
                    self.assertEqual(rss.fetch_entries("https://example.test/feed"), entrees)

    def test_un_flux_vide_en_200_reste_vide(self):
        with mock.patch.object(rss.feedparser, "parse", return_value=self.parse(status=200)):
            self.assertEqual(rss.fetch_entries("https://example.test/feed"), [])


if __name__ == "__main__":
    unittest.main()
