import tempfile
import unittest
from pathlib import Path
from unittest import mock

import data_paths


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.install_tmp = tempfile.TemporaryDirectory()
        self.data_tmp = tempfile.TemporaryDirectory()
        self.install_dir = Path(self.install_tmp.name)
        self.data_dir = Path(self.data_tmp.name)
        self.install_patch = mock.patch.object(data_paths, "INSTALL_DIR", self.install_dir)
        self.data_patch = mock.patch.object(data_paths, "DATA_DIR", self.data_dir)
        self.install_patch.start()
        self.data_patch.start()

    def tearDown(self):
        self.install_patch.stop()
        self.data_patch.stop()
        self.install_tmp.cleanup()
        self.data_tmp.cleanup()

    def test_migre_fichiers_et_dossier_herites(self):
        (self.install_dir / "config.json").write_text('{"lang": "fr"}', encoding="utf-8")
        (self.install_dir / "notification_history.json").write_text("[]", encoding="utf-8")
        (self.install_dir / ".watch2notif.lock").write_bytes(b"0")
        (self.install_dir / "state").mkdir()
        (self.install_dir / "state" / "watch2notif_issues.json").write_text('{"seen": []}', encoding="utf-8")

        data_paths.migrer_donnees_existantes()

        self.assertEqual((self.data_dir / "config.json").read_text(encoding="utf-8"), '{"lang": "fr"}')
        self.assertTrue((self.data_dir / "notification_history.json").exists())
        self.assertTrue((self.data_dir / ".watch2notif.lock").exists())
        self.assertEqual(
            (self.data_dir / "state" / "watch2notif_issues.json").read_text(encoding="utf-8"),
            '{"seen": []}',
        )
        self.assertFalse((self.install_dir / "config.json").exists())
        self.assertFalse((self.install_dir / "state").exists())

    def test_installation_neuve_ne_fait_rien(self):
        data_paths.migrer_donnees_existantes()

        self.assertEqual(list(self.data_dir.glob("*")), [(self.data_dir / ".migrated_from_install_dir")])

    def test_second_appel_ne_fait_rien(self):
        (self.install_dir / "config.json").write_text("premiere", encoding="utf-8")
        data_paths.migrer_donnees_existantes()

        # Un fichier reapparait dans l'ancien dossier (ex: un reinstallateur
        # maladroit) : le marqueur pose par le premier appel doit empecher
        # tout second passage, meme si l'ancien dossier n'est plus vide.
        (self.install_dir / "config.json").write_text("seconde", encoding="utf-8")
        data_paths.migrer_donnees_existantes()

        self.assertEqual((self.data_dir / "config.json").read_text(encoding="utf-8"), "premiere")

    def test_ne_pas_ecraser_une_donnee_deja_presente_a_la_cible(self):
        # Reproduit l'incident du 2026-09-17 : un config.json plus recent
        # existe deja dans DATA_DIR (ecrit par un run precedent) au moment
        # ou un vieux config.json traine encore dans INSTALL_DIR.
        (self.data_dir / "config.json").write_text("reel_actuel", encoding="utf-8")
        (self.install_dir / "config.json").write_text("vieux_perime", encoding="utf-8")

        data_paths.migrer_donnees_existantes()

        self.assertEqual((self.data_dir / "config.json").read_text(encoding="utf-8"), "reel_actuel")


if __name__ == "__main__":
    unittest.main()
