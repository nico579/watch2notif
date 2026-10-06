import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import data_paths

RACINE = Path(__file__).resolve().parent.parent


def _data_dir_au_chargement(env: dict) -> Path:
    """DATA_DIR tel que le calcule un processus neuf (la valeur est figée à
    l'import, le module déjà chargé ici ne la recalculerait pas)."""
    sortie = subprocess.run(
        [sys.executable, "-c", "import data_paths; print(data_paths.DATA_DIR)"],
        cwd=RACINE, env=env, capture_output=True, text=True, check=True)
    return Path(sortie.stdout.strip())


class DossierDonneesTests(unittest.TestCase):
    def test_watch2notif_home_l_emporte(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, WATCH2NOTIF_HOME=tmp)
            self.assertEqual(_data_dir_au_chargement(env), Path(tmp).resolve())

    def test_sans_variable_dossier_standard_de_l_os(self):
        from platformdirs import user_data_dir
        env = {k: v for k, v in os.environ.items() if k != "WATCH2NOTIF_HOME"}
        self.assertEqual(_data_dir_au_chargement(env),
                         Path(user_data_dir("watch2notif", appauthor=False)).resolve())


class MigrationTests(unittest.TestCase):
    """La reprise elle-meme est dans nico579_commons.dossiers (testee la-bas) ;
    ici, ce que watch2notif y met : ses fichiers, son marqueur, et l'appel
    depuis ses propres chemins."""

    def setUp(self):
        self.install_tmp = tempfile.TemporaryDirectory()
        self.data_tmp = tempfile.TemporaryDirectory()
        self.install_dir = Path(self.install_tmp.name).resolve()
        self.data_dir = Path(self.data_tmp.name).resolve()
        # Hors WATCH2NOTIF_HOME (qui desactive la reprise) : on vise le dossier
        # standard, remplace par un dossier temporaire.
        env = {k: v for k, v in os.environ.items() if k != "WATCH2NOTIF_HOME"}
        for patch in (mock.patch.dict(os.environ, env, clear=True),
                      mock.patch.object(data_paths.DOSSIERS, "dossier_etat_standard",
                                        return_value=self.data_dir)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.install_tmp.cleanup)
        self.addCleanup(self.data_tmp.cleanup)

    def _preparer(self):
        return data_paths.DOSSIERS.preparer_etat(self.install_dir)

    def test_reprend_fichiers_et_dossier_herites(self):
        (self.install_dir / "config.json").write_text('{"lang": "fr"}', encoding="utf-8")
        (self.install_dir / "notification_history.json").write_text("[]", encoding="utf-8")
        (self.install_dir / ".watch2notif.lock").write_bytes(b"0")
        (self.install_dir / "state").mkdir()
        (self.install_dir / "state" / "watch2notif_issues.json").write_text('{"seen": []}', encoding="utf-8")

        self._preparer()

        self.assertEqual((self.data_dir / "config.json").read_text(encoding="utf-8"), '{"lang": "fr"}')
        self.assertTrue((self.data_dir / "notification_history.json").exists())
        self.assertTrue((self.data_dir / ".watch2notif.lock").exists())
        self.assertEqual(
            (self.data_dir / "state" / "watch2notif_issues.json").read_text(encoding="utf-8"),
            '{"seen": []}',
        )
        # Copie, jamais deplacement : revenir a l'ancienne version reste possible.
        self.assertTrue((self.install_dir / "config.json").exists())
        self.assertTrue((self.data_dir / ".watch2notif_etat_migre.json").is_file())

    def test_installation_neuve_ne_fait_rien(self):
        self.assertEqual(self._preparer(), [])
        # Rien repris : pas de marqueur (l'examen recommence au lancement suivant).
        # Le fichier .lock du verrou peut rester, il ne contient aucune donnee.
        self.assertEqual([p.name for p in self.data_dir.glob("*") if p.suffix != ".lock"], [])

    def test_second_appel_ne_fait_rien(self):
        (self.install_dir / "config.json").write_text("premiere", encoding="utf-8")
        self._preparer()

        # Un fichier reapparait dans l'ancien dossier (ex: un reinstallateur
        # maladroit) : le marqueur pose par le premier appel doit empecher
        # tout second passage.
        (self.install_dir / "config.json").write_text("seconde", encoding="utf-8")
        (self.data_dir / "config.json").unlink()
        self.assertEqual(self._preparer(), [])

        self.assertFalse((self.data_dir / "config.json").exists())

    def test_ne_pas_ecraser_une_donnee_deja_presente_a_la_cible(self):
        # Reproduit l'incident du 2026-09-17 : un config.json plus recent
        # existe deja dans DATA_DIR (ecrit par un run precedent) au moment
        # ou un vieux config.json traine encore dans INSTALL_DIR.
        (self.data_dir / "config.json").write_text("reel_actuel", encoding="utf-8")
        (self.install_dir / "config.json").write_text("vieux_perime", encoding="utf-8")

        self._preparer()

        self.assertEqual((self.data_dir / "config.json").read_text(encoding="utf-8"), "reel_actuel")

    def test_watch2notif_home_desactive_la_reprise(self):
        (self.install_dir / "config.json").write_text("x", encoding="utf-8")
        with mock.patch.dict(os.environ, {"WATCH2NOTIF_HOME": str(self.data_dir)}):
            self.assertEqual(self._preparer(), [])
        self.assertFalse((self.data_dir / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
