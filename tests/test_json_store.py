"""Regression des ecritures/lectures JSON concurrentes (json_store).

Serveur HTTP, boucle de poll et autres threads partagent les memes
fichiers : temporaire au nom fixe partage entre ecrivains, refus Windows
passager pendant un remplacement, defaut rendu sur une lecture ratee puis
reecrit (constate le 2026-09-24)."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import json_store
import notifier


class JsonStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.dossier = Path(self.tempdir.name)
        self.cible = self.dossier / "config.json"

    def test_absent_corrompu_et_strict(self):
        self.assertEqual(json_store.read_json(self.cible, {"d": 1}), {"d": 1})
        self.cible.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(json_store.read_json(self.cible, []), [])
        with self.assertRaises(ValueError):
            json_store.read_json(self.cible, None, tolerate_corrupt=False)

    def test_refus_passager_retente_refus_persistant_leve(self):
        json_store.write_json_atomic(self.cible, {"a": 1})
        refus = PermissionError(13, "Access is denied")
        original = Path.read_text
        restants = [2]

        def lire(chemin, *args, **kwargs):
            if restants[0]:
                restants[0] -= 1
                raise refus
            return original(chemin, *args, **kwargs)

        with mock.patch.object(Path, "read_text", lire), \
                mock.patch.object(json_store.time, "sleep"):
            self.assertEqual(json_store.read_json(self.cible, {}), {"a": 1})
        with mock.patch.object(Path, "read_text", side_effect=refus), \
                mock.patch.object(json_store.time, "sleep"):
            with self.assertRaises(PermissionError):
                json_store.read_json(self.cible, {})

    def test_ecrivains_simultanes_sans_erreur_ni_residu(self):
        erreurs = []
        depart = threading.Barrier(4)

        def ecrire():
            depart.wait()
            for i in range(50):
                try:
                    json_store.write_json_atomic(self.cible, {"i": i})
                except Exception as exc:  # tout echec compte
                    erreurs.append(exc)

        fils = [threading.Thread(target=ecrire) for _ in range(4)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        self.assertEqual(erreurs, [])
        self.assertEqual(sorted(p.name for p in self.dossier.iterdir()), ["config.json"])

    def test_lecture_pendant_un_remplacement_attend(self):
        """Semantique Windows simulee partout : lire une cible en cours de
        remplacement echoue. Le remplacement dure 0,2 s et la lecture part
        exactement pendant : elle doit rendre la nouvelle valeur."""
        json_store.write_json_atomic(self.cible, {"a": 1})
        lire_original, remplacer_original = Path.read_text, os.replace
        en_cours = threading.Event()

        def lire(chemin, *args, **kwargs):
            if en_cours.is_set():
                raise PermissionError(13, "Access is denied")
            return lire_original(chemin, *args, **kwargs)

        def remplacer(source, cible):
            en_cours.set()
            try:
                time.sleep(0.2)
                return remplacer_original(source, cible)
            finally:
                en_cours.clear()

        with mock.patch.object(Path, "read_text", lire), \
                mock.patch.object(json_store.os, "replace", remplacer):
            ecrivain = threading.Thread(
                target=json_store.write_json_atomic, args=(self.cible, {"a": 2}))
            ecrivain.start()
            self.assertTrue(en_cours.wait(5))
            lu = json_store.read_json(self.cible, {})
            ecrivain.join()
        self.assertEqual(lu, {"a": 2})


class SaveConfigConcurrentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        config_file = Path(self.tempdir.name) / "config.json"
        patch = mock.patch.object(notifier, "CONFIG_FILE", config_file)
        patch.start()
        self.addCleanup(patch.stop)

    def test_enregistrements_simultanes_sans_erreur(self):
        # L'ancien config.json.tmp au nom fixe : le second os.replace trouvait
        # le temporaire deja consomme par le premier (FileNotFoundError).
        erreurs = []
        depart = threading.Barrier(4)

        def enregistrer():
            depart.wait()
            for _ in range(50):
                try:
                    notifier.save_config({"poll_interval_seconds": 60, "feeds": []})
                except Exception as exc:  # tout echec compte
                    erreurs.append(exc)

        fils = [threading.Thread(target=enregistrer) for _ in range(4)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        self.assertEqual(erreurs, [])
        self.assertEqual(notifier.load_config()["feeds"], [])


if __name__ == "__main__":
    unittest.main()
