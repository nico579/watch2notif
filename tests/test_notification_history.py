"""Regression du verrou entre append() (thread de poll) et clear() (route
HTTP /api/clear-history) : sans lui, un append() qui a lu l'etat avant un
clear() concurrent le reecrit juste apres, faisant reapparaitre les entrees
qu'on venait de vider (trouve en audit)."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import notification_history


class HistoryLockTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.history_file = Path(self.tempdir.name) / "notification_history.json"
        self.patch = mock.patch.object(notification_history, "HISTORY_FILE", self.history_file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tempdir.cleanup()

    def test_clear_waits_for_an_in_flight_append_instead_of_racing_it(self):
        entered_save = threading.Event()
        release_save = threading.Event()
        original_save = notification_history._save

        def _save_controlee(entries):
            entered_save.set()
            release_save.wait(timeout=2)
            original_save(entries)

        with mock.patch.object(notification_history, "_save", side_effect=_save_controlee):
            append_thread = threading.Thread(
                target=notification_history.append,
                args=("Feed", "Title", "Author", "Summary", "https://x.test"),
            )
            append_thread.start()
            self.assertTrue(entered_save.wait(timeout=2), "append() devrait avoir atteint _save()")

            # append() tient le verrou et est bloque dans _save(). clear(),
            # sur un autre thread, doit attendre qu'il le relache plutot
            # que d'ecrire en parallele : sans le verrou, clear() finirait
            # avant append(), qui reecrirait l'entree juste apres.
            clear_finished = threading.Event()
            clear_thread = threading.Thread(
                target=lambda: (notification_history.clear(), clear_finished.set())
            )
            clear_thread.start()
            self.assertFalse(
                clear_finished.wait(timeout=0.2),
                "clear() n'aurait pas du pouvoir s'executer pendant que append() tient le verrou",
            )

            release_save.set()
            append_thread.join(timeout=2)
            clear_thread.join(timeout=2)

        self.assertTrue(clear_finished.is_set())
        # clear() a attendu la fin de append() puis s'est applique en
        # dernier : l'historique reste vide, l'entree de append() n'a pas
        # reapparu apres coup.
        self.assertEqual(notification_history.load(), [])

    def test_lecture_ratee_n_efface_pas_l_historique(self):
        # append() relisait avec load(), qui rendait [] sur toute erreur : un
        # refus Windows (fichier en cours de remplacement) reecrivait alors
        # l'historique reduit a la seule nouvelle entree (2026-09-24).
        avant = [{"feed_label": "F", "title": f"t{i}", "author": "a",
                  "summary": "", "link": "", "timestamp": 1.0} for i in range(3)]
        self.history_file.write_text(json.dumps(avant), encoding="utf-8")
        original = Path.read_text

        def lire(chemin, *args, **kwargs):
            if Path(chemin) == self.history_file:
                raise PermissionError(13, "Access is denied")
            return original(chemin, *args, **kwargs)

        with mock.patch.object(Path, "read_text", lire), \
                mock.patch("time.sleep"):
            # Ne leve pas : appele apres le toast, une exception remonterait
            # dans le poll alors que la notification est deja partie.
            notification_history.append("Feed", "Nouveau", "Auteur", "", "https://x.test")
        self.assertEqual(json.loads(self.history_file.read_text(encoding="utf-8")), avant)


if __name__ == "__main__":
    unittest.main()
