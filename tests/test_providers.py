"""Providers desktop alignes sur leurs jumeaux Android (providers/ et
android/.../*Provider.java). Aucun appel reseau : la reponse est simulee."""
import json
import unittest
from unittest import mock

import config_transfer
from providers import github_discussion, youtube_comments


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


if __name__ == "__main__":
    unittest.main()
