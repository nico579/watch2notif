import tempfile
import unittest
from pathlib import Path

from nico579_commons import maj_install
from nico579_commons.maj_archive import ErreurMiseAJour

import self_update


def make_layout(parent: Path, system="Windows", archive_kind="zip") -> maj_install.Disposition:
    install = parent / "watch2notif"
    install.mkdir(parents=True)
    if system == "Darwin":
        return maj_install.Disposition(
            system="Darwin",
            machine="arm64",
            asset_name="watch2notif-macos-arm64.zip",
            archive_kind="zip",
            expected_root="watch2notif.app",
            install_root=install,
            data_relative=Path("Contents/MacOS"),
            executable_relative=Path("Contents/MacOS/watch2notif"),
        )
    return maj_install.Disposition(
        system=system,
        machine="x86_64",
        asset_name=f"watch2notif-{system.lower()}-x86_64." + ("zip" if archive_kind == "zip" else "tar.gz"),
        archive_kind=archive_kind,
        expected_root="watch2notif",
        install_root=install,
        data_relative=Path("."),
        executable_relative=Path("watch2notif.exe" if system == "Windows" else "watch2notif"),
    )


class TargetTests(unittest.TestCase):
    def test_supported_targets_are_exact(self):
        self.assertEqual(
            self_update.target_for("Windows", "AMD64")[0],
            "watch2notif-windows-x86_64.zip",
        )
        self.assertEqual(
            self_update.target_for("Linux", "x86_64")[0],
            "watch2notif-linux-x86_64.tar.gz",
        )
        self.assertEqual(
            self_update.target_for("Darwin", "arm64")[0],
            "watch2notif-macos-arm64.zip",
        )

    def test_unsupported_targets_do_not_fall_back(self):
        for system, machine in (("Windows", "ARM64"), ("Linux", "aarch64"), ("Darwin", "x86_64")):
            with self.subTest(system=system, machine=machine):
                with self.assertRaises(ErreurMiseAJour) as refus:
                    self_update.target_for(system, machine)
                self.assertEqual(refus.exception.code, "unsupported_target")

    def test_source_checkout_is_never_an_install_target(self):
        with self.assertRaises(ErreurMiseAJour) as refus:
            self_update.install_layout(frozen=False)
        self.assertEqual(refus.exception.code, "source_mode")

    def test_install_layout_requires_a_dedicated_clean_onedir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dedicated = root / "watch2notif"
            dedicated.mkdir()
            (dedicated / "_internal").mkdir()
            executable = dedicated / "watch2notif.exe"
            executable.touch()
            layout = self_update.install_layout(
                executable=executable,
                system="Windows",
                machine="AMD64",
                frozen=True,
            )
            self.assertEqual(layout.install_root, dedicated.resolve())

            (dedicated / "personal-file.txt").touch()
            with self.assertRaisesRegex(ErreurMiseAJour, "contenu inconnu"):
                self_update.install_layout(
                    executable=executable,
                    system="Windows",
                    machine="AMD64",
                    frozen=True,
                )

    def test_install_layout_tolerates_every_preserved_name(self):
        # Chaque fichier que l'appli persiste a cote de l'executable (cf
        # PRESERVED_NAMES) doit rester tolere par le garde-fou "contenu
        # inconnu", sinon la mise a jour automatique se bloque en silence
        # (constate en prod : notification_history.json manquant a la liste).
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dedicated = root / "watch2notif"
            dedicated.mkdir()
            (dedicated / "_internal").mkdir()
            executable = dedicated / "watch2notif.exe"
            executable.touch()
            for name in self_update.PRESERVED_NAMES:
                (dedicated / name).touch()
            layout = self_update.install_layout(
                executable=executable,
                system="Windows",
                machine="AMD64",
                frozen=True,
            )
            self.assertEqual(layout.install_root, dedicated.resolve())

    def test_install_layout_refuses_to_replace_a_generic_parent_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            generic = Path(temporary) / "Downloads"
            generic.mkdir()
            (generic / "_internal").mkdir()
            executable = generic / "watch2notif.exe"
            executable.touch()
            with self.assertRaisesRegex(ErreurMiseAJour, "dossier non dedie"):
                self_update.install_layout(
                    executable=executable,
                    system="Windows",
                    machine="AMD64",
                    frozen=True,
                )


if __name__ == "__main__":
    unittest.main()
