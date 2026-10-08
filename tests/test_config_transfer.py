import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import config_transfer


class PortableConfigTests(unittest.TestCase):
    def source(self, **changes):
        return dict(key="rss", label="Feed", kind="rss", url="https://example.org/feed", enabled=True,
                    interval_seconds=60, filtre_ia="Questions only", **changes)

    def test_only_sources_cross_devices_and_filter_rule_is_preserved(self):
        config = {"feeds": [self.source()], "credentials": {"github_token": "never-export-this"},
                  "history": [{"title": "private"}], "lang": "fr", "autostart_enabled": True}
        result = config_transfer.portable_config(config)
        self.assertEqual(set(result), {"poll_interval_seconds", "feeds"})
        self.assertEqual(result["feeds"][0]["filtre_ia"], "Questions only")
        self.assertNotIn("never-export-this", json.dumps(result))

    def test_android_fixture_round_trips_all_five_provider_types(self):
        vector = json.loads((Path(__file__).parent / "fixtures/pairing_vector.json").read_text(encoding="utf-8"))
        config = vector["expected"]
        result = config_transfer.portable_config(config)
        self.assertEqual({row["kind"] for row in result["feeds"]}, config_transfer.KINDS)
        self.assertEqual([row["filtre_ia"] for row in result["feeds"]], [row["filtre_ia"] for row in config["feeds"]])

    def test_empty_desktop_examples_are_skipped_and_null_interval_uses_provider_default(self):
        row = self.source(); row["interval_seconds"] = None
        result = config_transfer.portable_config({"feeds": [dict(row, url=""), row]})
        self.assertEqual(len(result["feeds"]), 1)
        self.assertEqual(result["feeds"][0]["interval_seconds"], 60)

    def test_hostile_keys_and_duplicate_keys_never_address_the_same_state(self):
        row = self.source()
        result = config_transfer.portable_config({"feeds": [dict(row, key="../escape"), row, row]})
        keys = [row["key"] for row in result["feeds"]]
        self.assertEqual(len(set(keys)), 3)
        self.assertTrue(all("/" not in key for key in keys))

    def test_invalid_imports_are_rejected_without_modifying_input(self):
        for change in ({"url": "file:///tmp/x"}, {"kind": "unknown"}, {"interval_seconds": True},
                       {"interval_seconds": -1}, {"enabled": "false"}, {"filtre_ia": "x" * 4001}):
            original = {"feeds": [dict(self.source(), **change)]}
            before = copy.deepcopy(original)
            with self.assertRaises(ValueError): config_transfer.portable_config(original)
            self.assertEqual(before, original)

    def test_youtube_url_host_must_be_youtube(self):
        row = dict(self.source(), kind="youtube_comments", url="https://evil.example/watch?v=dQw4w9WgXcQ")
        with self.assertRaises(ValueError): config_transfer.portable_config({"feeds": [row]})


if __name__ == "__main__":
    unittest.main()
