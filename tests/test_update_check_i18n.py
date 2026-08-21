import json
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import i18n
import update_check


class UpdateCheckTests(unittest.TestCase):
    def test_release_assets_are_sanitized_cached_and_returned(self):
        release = {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/nico579/watch2notif/releases/tag/v99.0.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "watch2notif-windows-x86_64.zip",
                    "browser_download_url": "https://github.com/nico579/watch2notif/releases/download/v99.0.0/watch2notif-windows-x86_64.zip",
                    "size": 123,
                    "digest": "sha256:" + "a" * 64,
                    "state": "uploaded",
                    "unneeded_field": "not cached",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with mock.patch.object(update_check, "_interroger", return_value=release):
                info = update_check.disponible(base, force=True)
            self.assertEqual(info["version"], "99.0.0")
            self.assertEqual(info["assets"][0]["digest"], "sha256:" + "a" * 64)
            cache = json.loads((base / "state" / update_check.CACHE_FILE_NAME).read_text(encoding="utf-8"))
            self.assertNotIn("unneeded_field", cache["assets"][0])

    def test_draft_and_prerelease_are_never_offered(self):
        for field in ("draft", "prerelease"):
            release = {
                "tag_name": "v99.0.0",
                "html_url": "https://example.test",
                "draft": field == "draft",
                "prerelease": field == "prerelease",
                "assets": [],
            }
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                with mock.patch.object(update_check, "_interroger", return_value=release):
                    self.assertEqual(update_check.disponible(Path(temporary), force=True), {})


class TranslationTests(unittest.TestCase):
    def test_every_string_exists_in_english_and_french(self):
        for key, translations in i18n.STRINGS.items():
            with self.subTest(key=key):
                self.assertIn("en", translations)
                self.assertIn("fr", translations)
                self.assertTrue(translations["en"])
                self.assertTrue(translations["fr"])

    def test_placeholders_match_between_languages(self):
        formatter = string.Formatter()
        for key, translations in i18n.STRINGS.items():
            english = {name for _, name, _, _ in formatter.parse(translations["en"]) if name}
            french = {name for _, name, _, _ in formatter.parse(translations["fr"]) if name}
            with self.subTest(key=key):
                self.assertEqual(english, french)


if __name__ == "__main__":
    unittest.main()
