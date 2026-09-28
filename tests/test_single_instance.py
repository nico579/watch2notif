"""Verrou d'instance unique, avec un vrai second process : c'est ce que
voit le process relance par Redemarrer, qui demarre avant que l'ancien ne
soit sorti. Dossier temporaire, jamais le vrai DATA_DIR.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import single_instance

REPO = Path(__file__).resolve().parents[1]

AUTRE_PROCESS = (
    "import sys; sys.path.insert(0, sys.argv[1]); import single_instance; "
    "from pathlib import Path; print(single_instance.acquire(Path(sys.argv[2])))"
)


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        # Enregistre apres : relache le verrou avant d'effacer le dossier.
        self.addCleanup(single_instance.release)
        self.base = Path(dossier.name)

    def autre_process(self) -> str:
        resultat = subprocess.run([sys.executable, "-c", AUTRE_PROCESS, str(REPO), str(self.base)],
                                  capture_output=True, text=True, timeout=60)
        return resultat.stdout.strip()

    def test_release_laisse_le_verrou_au_process_relance(self):
        self.assertTrue(single_instance.acquire(self.base))
        self.assertEqual(self.autre_process(), "False")
        single_instance.release()
        self.assertEqual(self.autre_process(), "True")

    def test_release_sans_verrou_ne_fait_rien(self):
        single_instance.release()
        single_instance.release()
        self.assertTrue(single_instance.acquire(self.base))


if __name__ == "__main__":
    unittest.main()
