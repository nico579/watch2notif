"""Enregistrements de configuration concurrents (notifier.save_config).

Serveur HTTP, boucle de poll et autres threads partagent config.json :
l'ancien temporaire au nom fixe (config.json.tmp) faisait echouer le second
remplacement. L'ecriture atomique, la lecture tolerante et leurs reprises sur
refus passager sont celles de nico579_commons.atomique, eprouvees la ; ici,
seulement leur emploi par save_config."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import notifier


class SaveConfigConcurrentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        config_file = Path(self.tempdir.name) / "config.json"
        patch = mock.patch.object(notifier, "CONFIG_FILE", config_file)
        patch.start()
        self.addCleanup(patch.stop)

    def test_enregistrements_simultanes_sans_erreur(self):
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

    def test_config_corrompue_n_est_pas_remplacee_en_silence(self):
        # config.json peut encore se reparer a la main : load_config doit
        # lever, pas rendre la configuration par defaut (tolerer_corrompu=False).
        notifier.CONFIG_FILE.write_text("{pas du json", encoding="utf-8")
        with self.assertRaises(ValueError):
            notifier.load_config()


if __name__ == "__main__":
    unittest.main()
