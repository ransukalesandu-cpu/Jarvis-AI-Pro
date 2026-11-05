"""Cron expressions, trigger catch-up/budget/failure policy, run history, tool actions."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from jarvis.actions import proactive_triggers as tool
from jarvis.core import cron_expr, trigger_runs
from jarvis.core.cron_expr import CronError, next_after, parse
from jarvis.core.owner_store import OwnerStore
from jarvis.core.triggers import MAX_CONSECUTIVE_FAILURES, Trigger, TriggerRegistry

COLOMBO = ZoneInfo("Asia/Colombo")
NEW_YORK = ZoneInfo("America/New_York")


def _ts(y, m, d, hh, mm, tz=COLOMBO):
    return datetime(y, m, d, hh, mm, tzinfo=tz).timestamp()


def _nxt(expr, after, tz="Asia/Colombo"):
    return datetime.fromtimestamp(next_after(parse(expr), after, tz), ZoneInfo(tz))


class CronParseTests(unittest.TestCase):
    def test_invalid_expressions_are_rejected(self):
        for bad in ("", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *", "* * 0 * *",
                    "* * * 13 *", "* * * * 8", "5-1 * * * *", "*/0 * * * *", "a * * * *"):
            with self.assertRaises(CronError, msg=bad):
                parse(bad)

    def test_unknown_zone_is_rejected(self):
        with self.assertRaises(CronError):
            cron_expr.resolve_zone("Mars/Olympus")


class CronNextTests(unittest.TestCase):
    base = _ts(2026, 11, 5, 9, 0)          # Thursday

    def test_every_fifteen_minutes(self):
        self.assertEqual(_nxt("*/15 * * * *", self.base).strftime("%H:%M"), "09:15")

    def test_strictly_after(self):
        self.assertEqual(_nxt("0 9 * * *", self.base).strftime("%m-%d %H:%M"), "11-06 09:00")

    def test_weekday_range(self):
        # Thursday 09:00 -> next Mon-Fri 07:30 is Friday.
        self.assertEqual(_nxt("30 7 * * 1-5", self.base).strftime("%a %H:%M"), "Fri 07:30")

    def test_names_and_sunday_aliases(self):
        for expr in ("0 9 * * sun", "0 9 * * 0", "0 9 * * 7"):
            self.assertEqual(_nxt(expr, self.base).strftime("%a"), "Sun", expr)
        self.assertEqual(_nxt("0 0 1 jan *", self.base).strftime("%Y-%m-%d"), "2027-01-01")

    def test_step_from_start(self):
        self.assertEqual(_nxt("5/20 * * * *", self.base).strftime("%H:%M"), "09:05")
        self.assertEqual(_nxt("5/20 * * * *", _ts(2026, 11, 5, 9, 5)).strftime("%H:%M"), "09:25")

    def test_day_or_weekday_when_both_restricted(self):
        # 13th of the month OR any Friday.
        got = _nxt("0 12 13 * 5", _ts(2026, 11, 5, 9, 0))
        self.assertEqual((got.day, got.strftime("%a")), (6, "Fri"))

    def test_leap_day(self):
        self.assertEqual(_nxt("0 0 29 2 *", self.base).strftime("%Y-%m-%d"), "2028-02-29")

    def test_impossible_date_returns_none(self):
        self.assertIsNone(next_after(parse("0 0 31 2 *"), self.base, "Asia/Colombo"))

    def test_dst_gap_is_skipped_and_gap_day_keeps_local_time(self):
        # 2026-03-08 02:30 does not exist in New York; the next day runs at 02:30 local.
        after = _ts(2026, 3, 7, 12, 0, NEW_YORK)
        got = _nxt("30 2 * * *", after, "America/New_York")
        self.assertEqual(got.strftime("%m-%d %H:%M"), "03-07 02:30") if got.day == 7 else None
        after = _ts(2026, 3, 8, 0, 0, NEW_YORK)
        got = _nxt("30 2 * * *", after, "America/New_York")
        self.assertEqual(got.strftime("%m-%d %H:%M"), "03-09 02:30")

    def test_dst_fall_back_fires_once(self):
        # 01:30 happens twice on 2026-11-01 in New York; only one run per day.
        first = next_after(parse("30 1 * * *"), _ts(2026, 10, 31, 12, 0, NEW_YORK), "America/New_York")
        second = next_after(parse("30 1 * * *"), first, "America/New_York")
        self.assertEqual(datetime.fromtimestamp(second, NEW_YORK).strftime("%m-%d"), "11-02")


class CronTriggerTests(unittest.TestCase):
    def test_validation(self):
        Trigger(name="a", prompt="p", cron="*/5 * * * *").validate()
        with self.assertRaises(ValueError):
            Trigger(name="a", prompt="p", cron="nope").validate()
        with self.assertRaises(ValueError):
            Trigger(name="a", prompt="p", cron="* * * * *", daily_at="07:00").validate()
        with self.assertRaises(ValueError):
            Trigger(name="a", prompt="p", cron="* * * * *", tz="Mars/Olympus").validate()
        with self.assertRaises(ValueError):
            Trigger(name="a", prompt="p", cron="* * * * *", mode="shell").validate()
        with self.assertRaises(ValueError):
            Trigger(name="a", prompt="p", cron="* * * * *", catch_up="never").validate()

    def test_cron_fires_when_due_then_waits(self):
        reg = TriggerRegistry()
        start = _ts(2026, 11, 5, 9, 0)
        reg.register({"name": "tick", "prompt": "go", "cron": "*/10 * * * *",
                      "tz": "Asia/Colombo", "registered_at": start})
        self.assertEqual(reg.due(start + 60), [])
        self.assertEqual([t.name for t, _ in reg.due(start + 601)], ["tick"])
        reg.mark_fired("tick", start + 601)
        self.assertEqual(reg.due(start + 700), [])

    def test_catch_up_once_fires_late_and_skip_drops(self):
        start = _ts(2026, 11, 5, 9, 0)
        late = start + 3 * 3600 + 30       # app was closed for three hours
        for mode, expect in (("once", 1), ("skip", 0)):
            reg = TriggerRegistry()
            reg.register({"name": "brief", "prompt": "go", "cron": "0 10 * * *",
                          "tz": "Asia/Colombo", "catch_up": mode, "registered_at": start})
            self.assertEqual(len(reg.due(late)), expect, mode)

    def test_catch_up_skip_still_fires_inside_grace(self):
        start = _ts(2026, 11, 5, 9, 0)
        reg = TriggerRegistry()
        reg.register({"name": "brief", "prompt": "go", "cron": "0 10 * * *", "tz": "Asia/Colombo",
                      "catch_up": "skip", "registered_at": start})
        self.assertEqual(len(reg.due(_ts(2026, 11, 5, 10, 0) + 30)), 1)

    def test_budget_holds_extra_fires(self):
        reg = TriggerRegistry()
        reg.register({"name": "spam", "prompt": "go", "every_seconds": 30, "max_per_hour": 2,
                      "registered_at": 1000.0})
        now = 1000.0
        fired = 0
        for step in range(1, 10):
            now = 1000.0 + step * 31
            due = reg.due(now)
            if due:
                reg.mark_fired("spam", now)
                fired += 1
        self.assertEqual(fired, 2)

    def test_three_failures_disable_and_enable_resets(self):
        reg = TriggerRegistry()
        reg.register({"name": "x", "prompt": "go", "every_seconds": 60})
        results = [reg.record_result("x", False) for _ in range(MAX_CONSECUTIVE_FAILURES)]
        self.assertEqual(results, [False, False, True])
        self.assertFalse(reg.get("x").enabled)
        self.assertTrue(reg.set_enabled("x", True))
        self.assertEqual(reg.get("x").consecutive_failures, 0)
        reg.record_result("x", False)
        reg.record_result("x", True)
        self.assertEqual(reg.get("x").consecutive_failures, 0)

    def test_run_now_fires_once_ignoring_schedule(self):
        reg = TriggerRegistry()
        reg.register({"name": "later", "prompt": "go", "cron": "0 3 1 1 *", "registered_at": 1000.0})
        self.assertEqual(reg.due(2000.0), [])
        self.assertTrue(reg.request_run("later"))
        self.assertEqual(len(reg.due(2000.0)), 1)
        self.assertEqual(reg.due(2000.0), [])
        self.assertFalse(reg.request_run("missing"))

    def test_persistence_roundtrip_and_old_files_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "triggers.json"
            reg = TriggerRegistry(path)
            reg.register({"name": "weekly", "prompt": "go", "cron": "0 9 * * mon", "tz": "Asia/Colombo",
                          "mode": "task", "catch_up": "skip", "max_per_hour": 3}, source="user", persist=True)
            again = TriggerRegistry(path).get("weekly")
            self.assertEqual((again.cron, again.tz, again.mode, again.catch_up, again.max_per_hour),
                             ("0 9 * * mon", "Asia/Colombo", "task", "skip", 3))
            path.write_text('[{"name": "old", "prompt": "hi", "daily_at": "07:30"}]', encoding="utf-8")
            old = TriggerRegistry(path).get("old")
            self.assertEqual((old.mode, old.catch_up, old.cron), ("turn", "once", None))


class RunHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = OwnerStore(Path(self.tmp.name) / "owner.db")
        trigger_runs.reset_for_tests()

    def tearDown(self):
        trigger_runs.reset_for_tests()
        self.tmp.cleanup()

    def test_record_update_and_list_newest_first(self):
        rid = trigger_runs.record("a", "started", store=self.store)
        trigger_runs.update(rid, "ok", "spoken", store=self.store)
        trigger_runs.record("b", "failed", detail="boom", store=self.store)
        rows = trigger_runs.runs(store=self.store)
        self.assertEqual([r["name"] for r in rows], ["b", "a"])
        self.assertEqual(trigger_runs.runs("a", store=self.store)[0]["status"], "ok")

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            trigger_runs.record("a", "weird", store=self.store)

    def test_history_is_capped_per_trigger(self):
        with patch.object(trigger_runs, "KEEP_PER_TRIGGER", 5):
            for _ in range(9):
                trigger_runs.record("a", "ok", store=self.store)
            trigger_runs.record("b", "ok", store=self.store)
            self.assertEqual(len(trigger_runs.runs("a", 100, store=self.store)), 5)
            self.assertEqual(len(trigger_runs.runs("b", 100, store=self.store)), 1)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.reg = TriggerRegistry()
        patcher = patch.object(tool, "get_trigger_registry", return_value=self.reg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_cron_task_and_list(self):
        out = tool.proactive_triggers({"action": "create", "name": "weekly", "prompt": "summarise",
                                       "cron": "0 9 * * mon", "tz": "Asia/Colombo", "mode": "task"})
        self.assertIn("cron '0 9 * * mon'", out)
        self.assertIn("[background task]", out)
        self.assertIn("weekly", tool.proactive_triggers({"action": "list"}))

    def test_bad_cron_is_an_error_not_saved(self):
        with self.assertRaises(ValueError):
            tool.proactive_triggers({"action": "create", "name": "bad", "prompt": "p", "cron": "nope"})
        self.assertIsNone(self.reg.get("bad"))

    def test_daily_with_zone_becomes_cron(self):
        tool.proactive_triggers({"action": "create", "name": "d", "prompt": "p",
                                 "daily_at": "07:30", "tz": "Asia/Colombo"})
        self.assertEqual(self.reg.get("d").cron, "30 7 * * *")
        self.assertIsNone(self.reg.get("d").daily_at)

    def test_enable_disable_run_now(self):
        self.reg.register({"name": "t", "prompt": "p", "every_seconds": 60})
        self.assertIn("disabled", tool.proactive_triggers({"action": "disable", "name": "t"}))
        self.assertFalse(self.reg.get("t").enabled)
        self.assertIn("enabled", tool.proactive_triggers({"action": "enable", "name": "t"}))
        self.assertIn("run in a few seconds", tool.proactive_triggers({"action": "run_now", "name": "t"}))
        self.assertIn("No trigger", tool.proactive_triggers({"action": "enable", "name": "zzz"}))

    def test_scheduled_task_cannot_change_triggers(self):
        with patch.object(tool, "_called_by_scheduled_task", return_value=True):
            for action in ("create", "delete", "enable", "disable", "run_now"):
                out = tool.proactive_triggers({"action": action, "name": "t", "prompt": "p",
                                               "daily_at": "07:30"})
                self.assertEqual(out, "A scheduled task cannot change triggers.", action)
            self.assertNotIn("cannot", tool.proactive_triggers({"action": "list"}))

    def test_runs_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OwnerStore(Path(tmp) / "o.db")
            trigger_runs.reset_for_tests()
            trigger_runs.record("t", "ok", detail="spoken", store=store)
            with patch("jarvis.core.owner_store.get_owner_store", return_value=store):
                out = tool.proactive_triggers({"action": "runs", "name": "t"})
            trigger_runs.reset_for_tests()
        self.assertIn("t [turn] ok", out)


if __name__ == "__main__":
    unittest.main()
