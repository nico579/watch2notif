import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import self_update


DEPOT = "nico579/watch2notif"


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def make_layout(parent: Path, system="Windows", archive_kind="zip") -> self_update.InstallLayout:
    install = parent / "watch2notif"
    install.mkdir(parents=True)
    if system == "Darwin":
        return self_update.InstallLayout(
            system="Darwin",
            machine="arm64",
            asset_name="watch2notif-macos-arm64.zip",
            archive_kind="zip",
            expected_root="watch2notif.app",
            install_root=install,
            data_relative=Path("Contents/MacOS"),
            executable_relative=Path("Contents/MacOS/watch2notif"),
        )
    return self_update.InstallLayout(
        system=system,
        machine="x86_64",
        asset_name=f"watch2notif-{system.lower()}-x86_64." + ("zip" if archive_kind == "zip" else "tar.gz"),
        archive_kind=archive_kind,
        expected_root="watch2notif",
        install_root=install,
        data_relative=Path("."),
        executable_relative=Path("watch2notif.exe" if system == "Windows" else "watch2notif"),
    )


def asset_for(layout: self_update.InstallLayout, data: bytes) -> dict:
    return {
        "name": layout.asset_name,
        "browser_download_url": f"https://github.com/{DEPOT}/releases/download/v9.0.0/{layout.asset_name}",
        "size": len(data),
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "state": "uploaded",
    }


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
                with self.assertRaisesRegex(self_update.UpdateError, "unsupported"):
                    self_update.target_for(system, machine)

    def test_source_checkout_is_never_an_install_target(self):
        with self.assertRaisesRegex(self_update.UpdateError, "source_mode"):
            self_update.install_layout(frozen=False)

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
            with self.assertRaisesRegex(self_update.UpdateError, "contenu inconnu"):
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
            with self.assertRaisesRegex(self_update.UpdateError, "dossier non dedie"):
                self_update.install_layout(
                    executable=executable,
                    system="Windows",
                    machine="AMD64",
                    frozen=True,
                )


class PrepareTests(unittest.TestCase):
    """Le choix du fichier de release, le téléchargement et l'extraction sont
    testés dans nico579_commons (maj_archive) ; ici, ce que watch2notif y
    ajoute : sa disposition d'installation et la préparation de bout en bout."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.layout = make_layout(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_prepare_update_leaves_current_install_untouched(self):
        current_marker = self.layout.install_root / "old.txt"
        current_marker.write_text("old", encoding="utf-8")
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as zipped:
            zipped.writestr("watch2notif/watch2notif.exe", b"new")
            zipped.writestr("watch2notif/_internal/library.dat", b"new library")
        archive_data = archive_buffer.getvalue()
        asset = asset_for(self.layout, archive_data)
        info = {"version": "9.0.0", "assets": [asset]}
        prepared = self_update.prepare_update(
            info,
            DEPOT,
            layout=self.layout,
            opener=lambda *_args, **_kwargs: FakeResponse(archive_data, asset["browser_download_url"]),
            smoke_test=False,
        )
        try:
            self.assertEqual(current_marker.read_text(encoding="utf-8"), "old")
            self.assertEqual((prepared.payload_root / "watch2notif.exe").read_bytes(), b"new")
            (prepared.staging_root / "helper.ready").touch()
            (prepared.staging_root / "helper.go.ack").touch()
            self_update.commit_prepared_update(prepared)
            self.assertTrue((prepared.staging_root / "helper.go").is_file())
        finally:
            self_update.cleanup_prepared(prepared)


if __name__ == "__main__":
    unittest.main()
