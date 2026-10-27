"""Unit tests for the local day planner and its reminder integration."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import daily_planner as planner


class DailyPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = Path(self.temp_dir.name) / "daily_planner.json"
        self.env_patcher = patch.dict(os.environ, {"JARVIS_PLANNER_FILE": str(self.store)})
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.alarm_calls = []

        def fake_reminder(parameters):
            self.alarm_calls.append(dict(parameters))
            if parameters.get("action") == "cancel":
                return "Reminder cancelled."
            return "Reminder set for January 01 at 08:00 AM."

        self.reminder_patcher = patch.object(planner, "_reminder", side_effect=fake_reminder)
        self.reminder_patcher.start()
        self.addCleanup(self.reminder_patcher.stop)

    def _saved(self):
        return json.loads(self.store.read_text(encoding="utf-8"))

    def test_remember_undated_task_survives_and_can_be_recalled(self):
        result = planner.daily_planner({
            "operation": "remember",
            "title": "Submit the assignment",
            "notes": "Check the final page before sending",
        })
        self.assertIn("Remembered for later", result)
        saved = self._saved()["items"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["title"], "Submit the assignment")
        self.assertEqual(saved[0]["alarm_status"], "none")
        self.assertEqual(self.alarm_calls, [])

        recalled = planner.daily_planner({"operation": "checkin"})
        self.assertIn("Submit the assignment", recalled)
        self.assertIn("Remembered without a date", recalled)

    def test_plan_registers_an_os_alarm_for_each_timed_item(self):
        result = planner.daily_planner({
            "operation": "plan",
            "date": "2099-01-01",
            "items": [
                {"title": "Study physics", "time": "08:00", "duration_minutes": 90},
                {"title": "Take a break", "time": "08:00", "duration_minutes": 10},
                {"title": "Review ICT", "time": "11:00"},
            ],
        })
        self.assertIn("Saved 3 plan item(s)", result)
        saved = self._saved()["items"]
        self.assertEqual(len(saved), 3)
        self.assertEqual(sum(row["alarm_status"] == "scheduled" for row in saved), 3)
        scheduled = [call for call in self.alarm_calls if call["action"] == "reminder"]
        self.assertEqual(len(scheduled), 3)
        self.assertEqual({call["message"] for call in scheduled}, {"Study physics", "Take a break", "Review ICT"})

    def test_date_without_time_is_remembered_without_claiming_an_alarm(self):
        result = planner.daily_planner({
            "operation": "add",
            "title": "Submit application",
            "date": "2099-01-04",
        })
        self.assertIn("Remembered for later", result)
        saved = self._saved()["items"][0]
        self.assertEqual(saved["date"], "2099-01-04")
        self.assertFalse(saved["alarm_enabled"])
        self.assertEqual(saved["alarm_status"], "none")
        self.assertEqual(self.alarm_calls, [])

    def test_forget_cancels_future_alarm_before_deleting_item(self):
        planner.daily_planner({
            "operation": "add",
            "title": "Call the tutor",
            "date": "2099-01-05",
            "time": "09:15",
        })
        item = self._saved()["items"][0]
        result = planner.daily_planner({"operation": "forget", "item_id": item["id"][:6]})
        self.assertIn("Forgotten and removed", result)
        self.assertEqual(self._saved()["items"], [])
        self.assertEqual(self.alarm_calls[-1]["action"], "cancel")
        self.assertEqual(self.alarm_calls[-1]["message"], "Call the tutor")

    def test_forget_keeps_item_if_os_alarm_cannot_be_cancelled(self):
        planner.daily_planner({
            "operation": "add",
            "title": "Attend meeting",
            "date": "2099-01-06",
            "time": "10:00",
        })
        item = self._saved()["items"][0]
        with patch.object(planner, "_reminder", return_value="I couldn't find a matching pending OS reminder."):
            result = planner.daily_planner({"operation": "forget", "item_id": item["id"][:6]})
        self.assertIn("kept the item saved", result)
        self.assertEqual(len(self._saved()["items"]), 1)

    def test_complete_marks_item_and_cancels_future_alarm(self):
        planner.daily_planner({
            "operation": "add",
            "title": "Finish revision",
            "date": "2099-01-07",
            "time": "13:00",
        })
        item = self._saved()["items"][0]
        result = planner.daily_planner({"operation": "complete", "item_id": item["id"][:6]})
        self.assertIn("Marked completed", result)
        saved = self._saved()["items"][0]
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(self.alarm_calls[-1]["action"], "cancel")

    def test_corrupt_store_is_not_overwritten(self):
        self.store.write_text("{broken json", encoding="utf-8")
        result = planner.daily_planner({"operation": "remember", "title": "Must not overwrite"})
        self.assertIn("left untouched", result)
        self.assertEqual(self.store.read_text(encoding="utf-8"), "{broken json")

    def test_plan_rejects_invalid_date_without_creating_items(self):
        result = planner.daily_planner({
            "operation": "plan",
            "date": "not-a-date",
            "items": [{"title": "Study", "time": "08:00"}],
        })
        self.assertIn("Use YYYY-MM-DD", result)
        self.assertFalse(self.store.exists())
        self.assertEqual(self.alarm_calls, [])


if __name__ == "__main__":
    unittest.main()
