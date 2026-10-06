import string
import unittest

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


if __name__ == "__main__":
    unittest.main()
