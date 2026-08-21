import hashlib
import io
import stat
import tarfile
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


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.layout = make_layout(self.root)
        self.data = b"archive"
        self.asset = asset_for(self.layout, self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def test_selects_one_uploaded_asset_with_size_digest_and_repo_url(self):
        selected = self_update.select_asset({"assets": [self.asset]}, self.layout, DEPOT)
        self.assertEqual(selected["name"], self.layout.asset_name)

    def test_rejects_missing_or_duplicate_asset(self):
        with self.assertRaises(self_update.UpdateError):
            self_update.select_asset({"assets": []}, self.layout, DEPOT)
        with self.assertRaises(self_update.UpdateError):
            self_update.select_asset({"assets": [self.asset, self.asset]}, self.layout, DEPOT)

    def test_rejects_bad_digest_size_state_and_url(self):
        mutations = (
            {"digest": None},
            {"size": 0},
            {"state": "new"},
            {"browser_download_url": "http://example.test/update.zip"},
            {"browser_download_url": f"https://github.com/other/repo/releases/download/v1/{self.layout.asset_name}"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bad = {**self.asset, **mutation}
                with self.assertRaises(self_update.UpdateError):
                    self_update.select_asset({"assets": [bad]}, self.layout, DEPOT)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.layout = make_layout(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_download_is_published_only_after_integrity_checks(self):
        data = b"verified bytes"
        asset = asset_for(self.layout, data)
        destination = self.root / "update.zip"
        self_update.download_asset(
            asset,
            destination,
            opener=lambda *_args, **_kwargs: FakeResponse(data, asset["browser_download_url"]),
        )
        self.assertEqual(destination.read_bytes(), data)
        self.assertFalse((self.root / "update.zip.part").exists())

    def test_bad_digest_or_truncated_download_is_removed(self):
        data = b"expected"
        for received in (b"modified", b"short"):
            destination = self.root / f"bad-{len(received)}.zip"
            asset = asset_for(self.layout, data)
            response = FakeResponse(received, asset["browser_download_url"])
            response.headers = {}
            with self.assertRaises(self_update.UpdateError):
                self_update.download_asset(
                    asset,
                    destination,
                    opener=lambda *_args, response=response, **_kwargs: response,
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(".zip.part").exists())

    def test_redirect_must_stay_on_https_github_hosts(self):
        data = b"expected"
        asset = asset_for(self.layout, data)
        destination = self.root / "redirect.zip"
        with self.assertRaises(self_update.UpdateError):
            self_update.download_asset(
                asset,
                destination,
                opener=lambda *_args, **_kwargs: FakeResponse(data, "https://evil.example/update.zip"),
            )


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.layout = make_layout(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_zip(self, name: str, members: dict[str, bytes]) -> Path:
        archive = self.root / name
        with zipfile.ZipFile(archive, "w") as zipped:
            for member, contents in members.items():
                zipped.writestr(member, contents)
        return archive

    def test_valid_zip_extracts_expected_single_root(self):
        archive = self._write_zip(
            "valid.zip",
            {
                "watch2notif/watch2notif.exe": b"exe",
                "watch2notif/_internal/library.dat": b"library",
            },
        )
        payload = self_update.extract_archive(archive, self.root / "out", self.layout)
        self.assertEqual((payload / "watch2notif.exe").read_bytes(), b"exe")

    def test_zip_rejects_traversal_absolute_backslash_and_extra_root(self):
        cases = (
            {"../escape": b"x"},
            {"/absolute": b"x"},
            {"watch2notif\\..\\escape": b"x"},
            {"another-root/file": b"x"},
        )
        for index, members in enumerate(cases):
            with self.subTest(members=members):
                archive = self._write_zip(f"bad-{index}.zip", members)
                with self.assertRaises(self_update.UpdateError):
                    self_update.extract_archive(archive, self.root / f"out-{index}", self.layout)

    def test_zip_rejects_escaping_symlink(self):
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            info = zipfile.ZipInfo("watch2notif/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(info, "../../escape")
        with self.assertRaises(self_update.UpdateError):
            self_update.extract_archive(archive, self.root / "link-out", self.layout)

    def test_tar_rejects_traversal(self):
        layout = make_layout(self.root / "tar-parent", system="Linux", archive_kind="tar")
        archive = self.root / "bad.tar.gz"
        contents = b"escape"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("../escape")
            info.size = len(contents)
            tar.addfile(info, io.BytesIO(contents))
        with self.assertRaises(self_update.UpdateError):
            self_update.extract_archive(archive, self.root / "tar-out", layout)

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
