"""Demarrage automatique sous Windows : un raccourci .lnk dans le dossier
Demarrage, comme blink2video et lidar2map, a la place du script .vbs des
versions <= 0.2.3 (VBScript en cours de retrait de Windows, encodage qui
cassait les chemins accentues).

Le dossier Demarrage est toujours un dossier temporaire (APPDATA redirige).
Sous Windows, un test cree un vrai raccourci par PowerShell."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import autostart_manager


class RaccourciWindowsTests(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory(prefix="w2n-appdata-")
        self.addCleanup(dossier.cleanup)
        self.appdata = Path(dossier.name) / "Roaming é"
        for correctif in (mock.patch.dict(os.environ, {"APPDATA": str(self.appdata)}),
                          mock.patch.object(autostart_manager.platform, "system",
                                            return_value="Windows")):
            correctif.start()
            self.addCleanup(correctif.stop)
        self.lnk = autostart_manager._windows_startup_file()
        self.vbs = autostart_manager._windows_legacy_file()
        self.vbs.parent.mkdir(parents=True)

    def powershell_simule(self, reussi=True):
        """Remplace PowerShell : ecrit le raccourci comme le ferait Save()."""
        def lancer(commande, **options):
            if reussi:
                self.lnk.write_bytes(b"raccourci")
            return subprocess.CompletedProcess(commande, 0 if reussi else 1, stderr="refus")
        return mock.patch.object(autostart_manager.subprocess, "run", side_effect=lancer)

    def test_enable_cree_le_raccourci_et_retire_le_vbs(self):
        self.vbs.write_text("ancien", encoding="utf-8")
        with self.powershell_simule() as lancer:
            autostart_manager.enable()
        self.assertTrue(self.lnk.exists())
        self.assertFalse(self.vbs.exists())
        self.assertTrue(autostart_manager.is_enabled())
        commande = lancer.call_args.args[0]
        self.assertEqual(commande[:2], ["powershell", "-NoProfile"])
        self.assertIn("CreateShortcut", commande[-1])
        self.assertEqual(lancer.call_args.kwargs["creationflags"],
                         getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_echec_de_powershell_signale_et_garde_le_vbs(self):
        self.vbs.write_text("ancien", encoding="utf-8")
        with self.powershell_simule(reussi=False):
            with self.assertRaisesRegex(RuntimeError, "refus"):
                autostart_manager.enable()
        # Le demarrage de l'utilisateur ne disparait pas sur un echec.
        self.assertTrue(self.vbs.exists())

    def test_disable_retire_raccourci_et_vbs(self):
        self.lnk.write_bytes(b"raccourci")
        self.vbs.write_text("ancien", encoding="utf-8")
        autostart_manager.disable()
        self.assertFalse(self.lnk.exists())
        self.assertFalse(self.vbs.exists())
        self.assertFalse(autostart_manager.is_enabled())

    def test_ancien_vbs_seul_compte_comme_actif(self):
        self.vbs.write_text("ancien", encoding="utf-8")
        self.assertTrue(autostart_manager.is_enabled())

    def test_migration_remplace_le_vbs(self):
        self.vbs.write_text("ancien", encoding="utf-8")
        with self.powershell_simule():
            self.assertTrue(autostart_manager.migrer_ancien_demarrage())
        self.assertTrue(self.lnk.exists())
        self.assertFalse(self.vbs.exists())

    def test_migration_sans_vbs_n_active_rien(self):
        with self.powershell_simule() as lancer:
            self.assertFalse(autostart_manager.migrer_ancien_demarrage())
        lancer.assert_not_called()
        self.assertFalse(self.lnk.exists())

    @unittest.skipUnless(sys.platform == "win32", "raccourci .lnk : Windows seulement")
    def test_vrai_raccourci_cree_par_powershell(self):
        autostart_manager.enable()
        self.assertTrue(self.lnk.is_file())
        lecture = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
             + autostart_manager._chaine_ps(str(self.lnk))
             + "); Write-Output $s.TargetPath"],
            capture_output=True, text=True, check=True)
        self.assertEqual(Path(lecture.stdout.strip()),
                         Path(autostart_manager._notifier_command()[0]))


class MigrationHorsWindowsTests(unittest.TestCase):
    def test_rien_hors_windows(self):
        with mock.patch.object(autostart_manager.platform, "system", return_value="Linux"), \
                mock.patch.object(autostart_manager.subprocess, "run") as lancer:
            self.assertFalse(autostart_manager.migrer_ancien_demarrage())
        lancer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
