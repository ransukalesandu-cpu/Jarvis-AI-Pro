"""Tests for the background producers that feed the HUD's task panels.

Two properties matter:

1. **No fabrication** — a producer with nothing to report returns ``None``, and a
   producer that *fails* is reported as an error rather than as an empty world.
2. **Stable identity** — the ``key`` of a task does not change between polls, so
   the panel manager can update a card in place instead of flickering.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import unittest

from core.task_sources import (
    SourceTask,
    TaskSourceRegistry,
    default_sources,
    download_task,
    reminder_task,
)


def _intention(text="Stretch", trigger_type="time", trigger="2026-10-29T09:00"):
    return {
        "id": "prospective:1",
        "type": "prospective",
        "status": "active",
        "content": text,
        "trigger_type": trigger_type,
        "trigger": trigger,
    }


class TestReminderTask(unittest.TestCase):
    def test_nothing_pending_produces_no_task(self):
        self.assertIsNone(reminder_task([]))

    def test_a_pending_intention_becomes_a_reminder_panel(self):
        task = reminder_task([_intention("Call the bank")])
        self.assertIsInstance(task, SourceTask)
        self.assertEqual(task.kind, "reminder")
        self.assertEqual(task.title, "Call the bank")
        # The key is what lets the manager update this card instead of replacing it.
        self.assertEqual(task.key, "source:reminder")
        self.assertIn("29 Oct 09:00", task.subtitle)
        # A reminder has no measurable fraction of completion.
        self.assertIsNone(task.progress)

    def test_extra_intentions_are_counted_not_hidden(self):
        task = reminder_task([_intention("First"), _intention("Second")])
        self.assertEqual(task.title, "First")
        self.assertIn("+1 more", task.subtitle)
        self.assertIn("2 pending", task.detail)

    def test_event_and_project_triggers_are_described_verbatim(self):
        task = reminder_task([_intention("Send invoice", "event", "invoice paid")])
        self.assertIn("when invoice paid", task.subtitle)

    def test_blank_text_is_not_promoted_to_a_panel(self):
        self.assertIsNone(reminder_task([_intention("   ")]))

    def test_a_malformed_time_trigger_falls_back_to_the_raw_value(self):
        task = reminder_task([_intention("Odd", "time", "next tuesday")])
        self.assertIn("next tuesday", task.subtitle)


class TestDownloadTask(unittest.TestCase):
    def test_no_downloads_produces_no_task(self):
        self.assertIsNone(download_task(scan=lambda: {"active": [], "pending": []}))
        self.assertIsNone(download_task(scan=lambda: {}))

    def test_an_active_download_wins_over_a_queued_update(self):
        task = download_task(
            scan=lambda: {"active": ["Portal 2"], "pending": ["Half-Life"]}
        )
        self.assertEqual(task.kind, "download")
        self.assertEqual(task.title, "Portal 2")
        self.assertIn("DOWNLOADING", task.subtitle)
        # Steam reports a state flag, not a percentage — never invent one.
        self.assertIsNone(task.progress)

    def test_queued_updates_are_shown_when_nothing_is_downloading(self):
        task = download_task(scan=lambda: {"active": [], "pending": ["A", "B", "C"]})
        self.assertEqual(task.title, "A")
        self.assertIn("UPDATE QUEUED", task.subtitle)
        self.assertIn("3 waiting", task.subtitle)

    def test_the_task_key_is_stable_across_polls(self):
        first = download_task(scan=lambda: {"active": ["Portal 2"], "pending": []})
        second = download_task(scan=lambda: {"active": ["Portal 2"], "pending": []})
        self.assertEqual(first.key, second.key)


class TestTaskSourceRegistry(unittest.TestCase):
    def test_default_sources_are_the_two_real_subsystems(self):
        self.assertEqual(set(default_sources()), {"reminders", "downloads"})

    def test_scan_returns_tasks_sorted_by_key(self):
        registry = TaskSourceRegistry(
            {
                "downloads": lambda: SourceTask(key="source:download", kind="download", title="D"),
                "reminders": lambda: SourceTask(key="source:reminder", kind="reminder", title="R"),
            }
        )
        self.assertEqual([t.key for t in registry.scan()], ["source:download", "source:reminder"])

    def test_a_silent_source_is_simply_omitted(self):
        registry = TaskSourceRegistry({"reminders": lambda: None})
        self.assertEqual(registry.scan(), [])
        self.assertEqual(registry.errors, {})

    def test_a_failing_source_is_reported_as_an_error_not_as_empty(self):
        def broken():
            raise RuntimeError("memory store unreadable")

        registry = TaskSourceRegistry({"reminders": broken})
        self.assertEqual(registry.scan(), [])
        self.assertIn("reminders", registry.errors)
        self.assertIn("memory store unreadable", registry.errors["reminders"])

    def test_one_broken_source_does_not_hide_a_working_one(self):
        def broken():
            raise ValueError("nope")

        registry = TaskSourceRegistry(
            {
                "reminders": broken,
                "downloads": lambda: SourceTask(key="source:download", kind="download", title="D"),
            }
        )
        self.assertEqual([t.key for t in registry.scan()], ["source:download"])
        self.assertIn("reminders", registry.errors)
        self.assertEqual(registry.names(), ["reminders", "downloads"])


if __name__ == "__main__":
    unittest.main()
