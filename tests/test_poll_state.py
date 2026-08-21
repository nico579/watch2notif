import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import notifier


class FakeEntry:
    def __init__(self, entry_id, timestamp=None):
        self.id = entry_id
        self._data = {
            "title": f"entry-{entry_id}",
            "author": "test",
            "link": f"https://example.test/{entry_id}",
            "summary": "",
        }
        if timestamp is not None:
            self._data["updated_parsed"] = time.gmtime(timestamp)

    def get(self, key, default=None):
        return self._data.get(key, default)


class PollStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_patch = mock.patch.object(notifier, "STATE_DIR", self.root)
        self.state_patch.start()
        self.feed = {"key": "feed", "label": "Test feed"}
        self.now = int(time.time())

    def tearDown(self):
        self.state_patch.stop()
        self.temporary.cleanup()

    def state_path(self):
        return self.root / "feed.json"

    def read_state(self):
        return json.loads(self.state_path().read_text(encoding="utf-8"))

    def write_state(self, data):
        self.state_path().write_text(json.dumps(data), encoding="utf-8")

    def poll(self, entries, notify_side_effect=None):
        with (
            mock.patch.object(notifier, "fetch_entries", return_value=entries),
            mock.patch.object(notifier, "notify", side_effect=notify_side_effect) as send,
        ):
            notifier.poll_feed(self.feed)
        return send

    def test_first_run_seeds_ids_and_watermark_without_notifications(self):
        entries = [FakeEntry("newest", self.now - 10), FakeEntry("older", self.now - 100)]
        send = self.poll(entries)

        send.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["version"], 2)
        self.assertEqual(set(state["seen_ids"]), {"newest", "older"})
        self.assertEqual(state["pending_ids"], [])
        self.assertEqual(state["newest_timestamp"], self.now - 10)

    def test_legacy_migration_notifies_new_and_absorbs_old_backfill(self):
        self.write_state(["known"])
        entries = [
            FakeEntry("new", self.now - 10),
            FakeEntry("known", self.now - 1000),
            FakeEntry("old-backfill", self.now - 10_000),
        ]
        send = self.poll(entries)

        self.assertEqual([call.args[1].id for call in send.call_args_list], ["new"])
        state = self.read_state()
        self.assertEqual(set(state["seen_ids"]), {"known", "new", "old-backfill"})
        self.assertEqual(state["pending_ids"], [])
        self.assertGreaterEqual(state["newest_timestamp"], self.now - 10)
        self.assertLessEqual(state["newest_timestamp"], time.time())

    def test_legacy_without_overlap_uses_state_mtime_as_cutoff(self):
        self.write_state(["no-longer-in-window"])
        cutoff = self.now - 3600
        os.utime(self.state_path(), (cutoff, cutoff))
        entries = [
            FakeEntry("new", self.now - 60),
            FakeEntry("old-backfill", self.now - 7200),
        ]
        send = self.poll(entries)

        self.assertEqual([call.args[1].id for call in send.call_args_list], ["new"])
        self.assertIn("old-backfill", self.read_state()["seen_ids"])

    def test_legacy_cutoff_uses_newer_mtime_even_with_one_ancient_known_id(self):
        self.write_state(["ancient-known"])
        cutoff = self.now - 3600
        os.utime(self.state_path(), (cutoff, cutoff))
        entries = [
            FakeEntry("new", self.now - 60),
            FakeEntry("intermediate-backfill", self.now - 7200),
            FakeEntry("ancient-known", self.now - 20_000),
        ]
        send = self.poll(entries)

        self.assertEqual([call.args[1].id for call in send.call_args_list], ["new"])
        self.assertIn("intermediate-backfill", self.read_state()["seen_ids"])

    def test_future_legacy_mtime_is_clamped_and_does_not_hide_recent_entry(self):
        self.write_state(["gone"])
        future_mtime = self.now + 7 * 24 * 3600
        os.utime(self.state_path(), (future_mtime, future_mtime))
        send = self.poll([FakeEntry("recent", self.now - 60)])

        self.assertEqual([call.args[1].id for call in send.call_args_list], ["recent"])
        self.assertLessEqual(self.read_state()["newest_timestamp"], time.time())

    def test_source_fingerprint_change_reseeds_without_notifications(self):
        old_feed = {"key": "feed", "label": "Test feed", "kind": "rss", "url": "old"}
        new_feed = {"key": "feed", "label": "Test feed", "kind": "rss", "url": "new"}
        self.write_state(
            {
                "version": 2,
                "seen_ids": ["old-id"],
                "pending_ids": [],
                "newest_timestamp": self.now,
                "source_fingerprint": notifier._feed_fingerprint(old_feed),
            }
        )
        self.feed = new_feed
        send = self.poll([FakeEntry("new-source-old-item", self.now - 10_000)])

        send.assert_not_called()
        state = self.read_state()
        self.assertEqual(state["seen_ids"], ["new-source-old-item"])
        self.assertEqual(state["source_fingerprint"], notifier._feed_fingerprint(new_feed))

    def test_entry_within_grace_or_equal_to_watermark_is_not_suppressed(self):
        watermark = self.now - 100
        self.write_state(
            {"version": 2, "seen_ids": [], "pending_ids": [], "newest_timestamp": watermark}
        )
        entries = [
            FakeEntry("equal", watermark),
            FakeEntry("within-grace", watermark - notifier.BACKFILL_GRACE_SECONDS + 1),
        ]
        send = self.poll(entries)

        self.assertEqual(
            {call.args[1].id for call in send.call_args_list},
            {"equal", "within-grace"},
        )

    def test_old_unknown_entry_is_recorded_without_notification(self):
        watermark = self.now - 100
        self.write_state(
            {"version": 2, "seen_ids": ["known"], "pending_ids": [], "newest_timestamp": watermark}
        )
        send = self.poll([FakeEntry("old", watermark - 10_000)])

        send.assert_not_called()
        self.assertIn("old", self.read_state()["seen_ids"])

    def test_failed_notification_stays_pending_after_watermark_advances(self):
        watermark = self.now - 20_000
        self.write_state(
            {"version": 2, "seen_ids": ["base"], "pending_ids": [], "newest_timestamp": watermark}
        )
        entries = [
            FakeEntry("newest", self.now - 1000),
            FakeEntry("retry", self.now - 5000),
        ]

        def fail_retry(_label, entry):
            if entry.id == "retry":
                raise RuntimeError("backend down")

        first_send = self.poll(entries, notify_side_effect=fail_retry)
        self.assertEqual(len(first_send.call_args_list), 2)
        first_state = self.read_state()
        self.assertEqual(first_state["pending_ids"], ["retry"])
        self.assertIn("newest", first_state["seen_ids"])
        self.assertEqual(first_state["newest_timestamp"], self.now - 1000)

        second_send = self.poll([FakeEntry("retry", self.now - 5000)])
        self.assertEqual([call.args[1].id for call in second_send.call_args_list], ["retry"])
        second_state = self.read_state()
        self.assertIn("retry", second_state["seen_ids"])
        self.assertEqual(second_state["pending_ids"], [])

    def test_entry_without_timestamp_keeps_id_based_behavior(self):
        self.write_state(
            {"version": 2, "seen_ids": [], "pending_ids": [], "newest_timestamp": self.now}
        )
        send = self.poll([FakeEntry("undated")])
        self.assertEqual([call.args[1].id for call in send.call_args_list], ["undated"])

    def test_integer_ids_are_normalized_to_strings(self):
        self.write_state(
            {"version": 2, "seen_ids": ["42"], "pending_ids": [], "newest_timestamp": None}
        )
        send = self.poll([FakeEntry(42)])
        send.assert_not_called()

    def test_far_future_feed_date_is_ignored_but_persisted_watermark_survives_clock_changes(self):
        future = self.now + notifier.MAX_FUTURE_TIMESTAMP_SECONDS + 1
        self.assertIsNone(notifier._entry_timestamp(FakeEntry("future", future)))
        self.write_state(
            {"version": 2, "seen_ids": [], "pending_ids": [], "newest_timestamp": future}
        )
        self.assertEqual(notifier.load_feed_state("feed").newest_timestamp, future)


if __name__ == "__main__":
    unittest.main()
