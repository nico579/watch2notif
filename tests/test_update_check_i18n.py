import string
import unittest
from unittest import mock

import i18n


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


class SystemLanguageTests(unittest.TestCase):
    """detect_default_lang() without locale.getdefaultlocale(), removed in Python 3.15."""

    def test_language_codes(self):
        cases = {"fr_FR.UTF-8": "fr", "fr-CA": "fr", "fr": "fr", "fr_FR@euro": "fr",
                 "en_US.UTF-8": "en", "fy_NL": "fy", "C": "", "C.UTF-8": "", "POSIX": "", "": ""}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(i18n._code_langue(value), expected)

    def test_environment_is_read_in_gettext_order(self):
        cases = [({"LANGUAGE": "fr:en", "LANG": "en_US.UTF-8"}, "fr"),
                 ({"LC_ALL": "en_GB.UTF-8", "LANG": "fr_FR.UTF-8"}, "en"),
                 ({"LC_ALL": "C", "LANG": "fr_FR.UTF-8"}, "fr"),
                 ({}, "")]
        for environ, expected in cases:
            with self.subTest(environ=environ):
                self.assertEqual(i18n._langue_systeme("linux", environ), expected)

    def test_macos_app_without_lang_reads_apple_languages(self):
        # Launched from the Finder or by launchd, the app has no LANG.
        sortie = mock.Mock(stdout='(\n    "fr-FR",\n    en\n)\n')
        with mock.patch.object(i18n.subprocess, "run", return_value=sortie) as run:
            self.assertEqual(i18n._langue_systeme("darwin", {}), "fr")
        self.assertEqual(run.call_args.args[0], ["defaults", "read", "-g", "AppleLanguages"])

    def test_macos_with_lang_does_not_run_defaults(self):
        with mock.patch.object(i18n.subprocess, "run") as run:
            self.assertEqual(i18n._langue_systeme("darwin", {"LANG": "en_US.UTF-8"}), "en")
        run.assert_not_called()

    def test_first_apple_language(self):
        cases = {'(\n    "fr-FR",\n    en\n)': "fr-FR", "(\n    en,\n    fr\n)": "en", "": "", "()": ""}
        for output, expected in cases.items():
            with self.subTest(output=output):
                self.assertEqual(i18n._premiere_langue_apple(output), expected)

    def test_windows_uses_the_display_language_not_the_environment(self):
        windll = mock.Mock()
        for langid, expected in ((0x040C, "fr"), (0x0C0C, "fr"), (0x0409, ""), (0x0407, "")):
            windll.kernel32.GetUserDefaultUILanguage.return_value = langid
            with self.subTest(langid=hex(langid)), mock.patch("ctypes.windll", windll, create=True):
                # A LANG left by Git Bash or MSYS must not override Windows.
                self.assertEqual(i18n._langue_systeme("win32", {"LANG": "en_US.UTF-8"}), expected)

    def test_detect_default_lang_never_raises(self):
        i18n.detect_default_lang.cache_clear()
        self.addCleanup(i18n.detect_default_lang.cache_clear)
        with mock.patch.object(i18n, "_langue_systeme", side_effect=OSError("no defaults")):
            self.assertEqual(i18n.detect_default_lang(), "en")


if __name__ == "__main__":
    unittest.main()
