"""Providers desktop alignes sur leurs jumeaux Android (providers/ et
android/.../*Provider.java). Aucun appel reseau : la reponse est simulee."""
import json
import unittest
from unittest import mock

import config_transfer
from providers import github_comments, github_discussion, github_forks, github_issues, youtube_comments


class ReponseSimulee:
    def __init__(self, donnees):
        self._corps = json.dumps(donnees).encode("utf-8")

    def read(self):
        return self._corps

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DiscussionGitHub(unittest.TestCase):
    def test_demande_les_commentaires_les_plus_recents(self):
        # Une connexion GraphQL va du plus ancien au plus recent : first: 100
        # figeait la surveillance sur les 100 premiers commentaires d'un long fil.
        requetes = []

        def ouvrir(requete, timeout=None):
            requetes.append(json.loads(requete.data))
            return ReponseSimulee({"data": {"repository": {"discussion": {
                "title": "Fil", "comments": {"nodes": [{
                    "id": "C1", "databaseId": 1, "url": "https://github.com/o/r/discussions/1#c1",
                    "bodyText": "texte", "createdAt": "2026-10-01T00:00:00Z", "author": {"login": "a"},
                    "replies": {"nodes": []}}]}}}}})

        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "t"}), \
                mock.patch.object(github_discussion.urllib.request, "urlopen", side_effect=ouvrir):
            entrees = github_discussion.fetch_entries("o/r#1")
        requete = requetes[0]["query"]
        self.assertIn("comments(last: 100)", requete)
        self.assertIn("replies(last: 100)", requete)
        self.assertNotIn("first:", requete)
        self.assertEqual([e.id for e in entrees], ["1"])


class TexteEntier(unittest.TestCase):
    def test_le_filtre_ia_recoit_tout_le_texte(self):
        # notify() coupe pour l'affichage ; le filtre IA en lit jusqu'a TEXTE_MAX.
        long = "mot " * 200
        commentaire = {"id": "Ugx", "snippet": {"textOriginal": long, "authorDisplayName": "a",
                                                "publishedAt": "2026-10-01T00:00:00Z"}}
        noeud = {"id": "C1", "databaseId": 1, "url": "u", "bodyText": long,
                 "createdAt": "2026-10-01T00:00:00Z", "author": {"login": "a"}}
        for entree in (youtube_comments._to_entry(commentaire, "6rNqLI9K8Tc", "Video"),
                       github_discussion._to_entry(noeud, "Fil")):
            self.assertEqual(entree.get("summary"), long.strip())


class VideoYouTube(unittest.TestCase):
    def test_toute_url_acceptee_a_l_import_est_comprise(self):
        for url in ("https://www.youtube.com/watch?v=6rNqLI9K8Tc",
                    "https://www.youtube.com/watch?feature=share&v=6rNqLI9K8Tc&t=10",
                    "https://youtu.be/6rNqLI9K8Tc",
                    "https://www.youtube.com/embed/6rNqLI9K8Tc",
                    "https://www.youtube.com/shorts/6rNqLI9K8Tc",
                    "https://www.youtube.com/live/6rNqLI9K8Tc?si=x",
                    "6rNqLI9K8Tc"):
            with self.subTest(url=url):
                # Le format de transfert l'accepte : le provider doit le lire.
                config_transfer.portable_config({"feeds": [{"kind": "youtube_comments", "url": url}]})
                self.assertEqual(youtube_comments._extract_video_id(url), "6rNqLI9K8Tc")

    def test_un_identifiant_trop_long_est_refuse(self):
        with self.assertRaises(ValueError):
            youtube_comments._extract_video_id("https://www.youtube.com/watch?v=6rNqLI9K8TcXX")


class CommentairesGitHub(unittest.TestCase):
    # Jumeau de ProvidersTest.githubCommentsSkipTheOwnerAndBotsAndNameTheIssue.
    def test_ni_le_proprietaire_ni_les_robots_et_le_numero_de_l_issue(self):
        issues = "https://api.github.com/repos/nico579/watch2notif/issues/"
        donnees = [
            {"id": 11, "user": {"login": "MCas86", "type": "User"}, "issue_url": issues + "40",
             "html_url": "h", "body": "b", "created_at": "2026-10-17T15:11:11Z"},
            {"id": 12, "user": {"login": "Nico579", "type": "User"}, "issue_url": issues + "40"},
            {"id": 13, "user": {"login": "dependabot[bot]", "type": "Bot"}, "issue_url": issues + "41"},
            {"id": 14, "user": None, "issue_url": issues + "7"},
        ]
        requetes = []

        def ouvrir(requete, timeout=None):
            requetes.append(requete.full_url)
            return ReponseSimulee(donnees)

        with mock.patch.object(github_issues.urllib.request, "urlopen", side_effect=ouvrir):
            entrees = github_comments.fetch_entries("nico579/watch2notif")
        self.assertEqual([(e.id, e.get("title"), e.get("author")) for e in entrees],
                         [("11", "#40", "MCas86"), ("14", "#7", "?")])
        self.assertIn("/repos/nico579/watch2notif/issues/comments?sort=created&direction=desc", requetes[0])


class ForksGitHub(unittest.TestCase):
    # Jumeau de ProvidersTest.githubForksMakeANewEntryForEachPush.
    def test_chaque_poussee_fait_une_entree_nouvelle(self):
        fork = {"full_name": "TruncatedPi/blink2video_noModule", "owner": {"login": "TruncatedPi"},
                "html_url": "h", "description": None}

        def lire(pousse):
            with mock.patch.object(github_issues.urllib.request, "urlopen",
                                   return_value=ReponseSimulee([dict(fork, pushed_at=pousse)])):
                return github_forks.fetch_entries("nico579/blink2video")[0]

        premiere, suivante = lire("2026-10-10T01:34:03Z"), lire("2026-10-12T08:00:00Z")
        self.assertEqual(premiere.id, "TruncatedPi/blink2video_noModule@2026-10-10T01:34:03Z")
        self.assertNotEqual(premiere.id, suivante.id)
        self.assertEqual((premiere.get("author"), premiere.get("summary")), ("TruncatedPi", ""))


class TransfertDesNouvellesSources(unittest.TestCase):
    def test_un_depot_et_la_cadence_par_defaut(self):
        for kind, defaut in (("github_comments", 300), ("github_forks", 1800)):
            with self.subTest(kind=kind):
                ligne = config_transfer.portable_config(
                    {"feeds": [{"kind": kind, "url": "nico579/blink2video"}]})["feeds"][0]
                self.assertEqual((ligne["kind"], ligne["interval_seconds"]), (kind, defaut))
                with self.assertRaises(ValueError):
                    config_transfer.portable_config({"feeds": [{"kind": kind, "url": "https://example.org"}]})


if __name__ == "__main__":
    unittest.main()
