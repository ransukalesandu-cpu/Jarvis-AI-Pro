"""Proactive triggers: registry, schedules, quiet hours, persistence, scheduler gate."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

from jarvis.core import triggers as trig_mod  # noqa: E402
from jarvis.core.triggers import (  # noqa: E402
    Trigger, TriggerRegistry, in_quiet_hours, parse_quiet_hours,
)


def _at(hh: int, mm: int) -> float:
    return datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp()


class TriggerScheduleTests(unittest.TestCase):
    def test_validation_requires_exactly_one_schedule(self):
        with self.assertRaises(ValueError):
            Trigger(name="x", prompt="p").validate()
        with self.assertRaises(ValueError):
            Trigger(name="x", prompt="p", daily_at="07:00", every_seconds=60).validate()
        with self.assertRaises(ValueError):
            Trigger(name="bad name", prompt="p", daily_at="07:00").validate()
        with self.assertRaises(ValueError):
            Trigger(name="x", prompt="p", daily_at="25:00").validate()
        Trigger(name="ok", prompt="p", daily_at="07:30").validate()

    def test_daily_trigger_fires_once_per_day(self):
        reg = TriggerRegistry()
        reg.register({"name": "brief", "prompt": "Morning briefing", "daily_at": "07:30",
                      "registered_at": _at(6, 0)})
        self.assertEqual(reg.due(_at(7, 29)), [])
        due = reg.due(_at(7, 31))
        self.assertEqual([t.name for t, _ in due], ["brief"])
        reg.mark_fired("brief", _at(7, 31))
        self.assertEqual(reg.due(_at(9, 0)), [])

    def test_daily_trigger_registered_after_its_slot_waits_for_tomorrow(self):
        reg = TriggerRegistry()
        reg.register({"name": "brief", "prompt": "p", "daily_at": "07:30",
                      "registered_at": _at(8, 0)})
        self.assertEqual(reg.due(_at(8, 1)), [])

    def test_quiet_hours_cross_midnight(self):
        quiet = parse_quiet_hours("22:00-07:00")
        self.assertTrue(in_quiet_hours(quiet, datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(in_quiet_hours(quiet, datetime(2026, 1, 1, 6, 59)))
        self.assertFalse(in_quiet_hours(quiet, datetime(2026, 1, 1, 7, 0)))
        self.assertIsNone(parse_quiet_hours("nonsense"))

    def test_trigger_held_by_quiet_hours_fires_when_they_end(self):
        reg = TriggerRegistry()
        reg.register({"name": "r", "prompt": "p", "daily_at": "06:30",
                      "registered_at": _at(5, 0)})
        self.assertEqual(reg.due(_at(6, 45), quiet_hours="22:00-07:00"), [])
        self.assertEqual(len(reg.due(_at(7, 1), quiet_hours="22:00-07:00")), 1)

    def test_condition_trigger_and_broken_condition(self):
        reg = TriggerRegistry()
        reg.register(Trigger(name="cond", check=lambda: "Battery is at 9%."))
        reg.register(Trigger(name="broken", check=lambda: 1 / 0))
        self.assertEqual([p for _, p in reg.due()], ["Battery is at 9%."])

    def test_user_triggers_persist_and_one_shots_are_removed_after_firing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "triggers.json"
            reg = TriggerRegistry(path)
            reg.register({"name": "standup", "prompt": "p", "every_seconds": 600},
                         source="user", persist=True)
            reg.register({"name": "once", "prompt": "p", "once_at": time.time() - 1},
                         source="user", persist=True)
            reloaded = TriggerRegistry(path)
            self.assertEqual({t.name for t in reloaded.list()}, {"standup", "once"})
            reloaded.mark_fired("once")
            self.assertEqual({t.name for t in TriggerRegistry(path).list()}, {"standup"})

    def test_file_trigger_cannot_be_replaced_or_deleted_by_voice(self):
        reg = TriggerRegistry()
        reg.register({"name": "brief", "prompt": "p", "daily_at": "07:00"}, source="file")
        with self.assertRaises(ValueError):
            reg.register({"name": "brief", "prompt": "q", "daily_at": "08:00"}, source="user")
        self.assertFalse(reg.unregister("brief"))


class TriggerDiscoveryAndToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        trig_mod.reset_trigger_registry_for_tests(TriggerRegistry(Path(self.tmp.name) / "t.json"))

    def tearDown(self):
        trig_mod.reset_trigger_registry_for_tests(None)
        self.tmp.cleanup()

    def test_action_loader_registers_module_triggers(self):
        from jarvis.core.action_loader import discover_actions
        actions = Path(self.tmp.name) / "actions_pkg"
        actions.mkdir()
        (actions / "hourly_note.py").write_text(textwrap.dedent('''
            TRIGGERS = [{"name": "hourly_note", "prompt": "Say the time.", "every_seconds": 3600}]
        '''), encoding="utf-8")
        logs = []
        discover_actions(actions, logger=logs.append)
        sys.modules.pop("jarvis.actions.hourly_note", None)
        self.assertIsNotNone(trig_mod.get_trigger_registry().get("hourly_note"))
        self.assertTrue(any("Trigger registered: hourly_note" in line for line in logs))

    def test_voice_tool_create_list_delete(self):
        from jarvis.actions.proactive_triggers import proactive_triggers
        with patch("jarvis.actions.proactive_triggers.get_quiet_hours", return_value=""):
            out = proactive_triggers({"action": "create", "name": "water",
                                      "prompt": "Remind me to drink water.",
                                      "every_minutes": 45})
            self.assertIn("Trigger saved", out)
            self.assertIn("water", proactive_triggers({"action": "list"}))
            self.assertIn("Deleted", proactive_triggers({"action": "delete", "name": "water"}))
            self.assertNotIn("water:", proactive_triggers({"action": "list"}))


class _Host:
    """Just the state the scheduler reads, bound to the real mixin methods."""

    def __init__(self):
        from jarvis.core.runtime.live_services import BackgroundServicesMixin as M
        self._proactive_turn_blocker = M._proactive_turn_blocker.__get__(self)
        self._fire_trigger = M._fire_trigger.__get__(self)
        self._run_trigger_scheduler = M._run_trigger_scheduler.__get__(self)
        self.session = SimpleNamespace(send_client_content=AsyncMock())
        self._speaking_lock = threading.Lock()
        self._is_speaking = False
        self._assistant_turn_pending = False
        self._briefing_active = False
        self._interrupted = False
        self._inflight_user_text = ""
        self._last_user_speech = 0.0
        self._turn_done_event = None
        self._shutdown_requested = False
        self._awake = True
        self.ui = MagicMock()
        self.wake = MagicMock()


class TriggerSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = TriggerRegistry(Path(self.tmp.name) / "t.json")
        trig_mod.reset_trigger_registry_for_tests(self.reg)

    async def asyncTearDown(self):
        trig_mod.reset_trigger_registry_for_tests(None)
        self.tmp.cleanup()

    def test_blocker_never_talks_over_the_owner(self):
        host = _Host()
        self.assertEqual(host._proactive_turn_blocker(), "")
        host._last_user_speech = time.monotonic()
        self.assertEqual(host._proactive_turn_blocker(), "owner spoke recently")
        host._last_user_speech = 0.0
        host._is_speaking = True
        self.assertEqual(host._proactive_turn_blocker(), "jarvis speaking")
        host._is_speaking = False
        host._inflight_user_text = "what's the"
        self.assertEqual(host._proactive_turn_blocker(), "owner turn in progress")

    async def _run_scheduler(self, host, seconds=0.3):
        with patch("jarvis.core.runtime.live_services.TRIGGER_TICK_SECONDS", 0.05), \
             patch("jarvis.core.runtime.live_services.get_quiet_hours", return_value=""):
            task = asyncio.create_task(host._run_trigger_scheduler())
            await asyncio.sleep(seconds)
            host._shutdown_requested = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_due_trigger_makes_jarvis_speak_first(self):
        self.reg.register({"name": "reminder", "prompt": "Remind the owner to stretch.",
                           "once_at": time.time() - 1}, source="user", persist=True)
        host = _Host()
        await self._run_scheduler(host)
        host.session.send_client_content.assert_awaited_once()
        sent = host.session.send_client_content.await_args.kwargs
        self.assertTrue(sent["turn_complete"])
        self.assertIn("Remind the owner to stretch.", sent["turns"]["parts"][0]["text"])
        self.assertIsNone(self.reg.get("reminder"))   # one-shot removed after firing

    async def test_due_trigger_waits_while_owner_is_talking(self):
        self.reg.register({"name": "reminder", "prompt": "p", "once_at": time.time() - 1},
                          source="user", persist=True)
        host = _Host()
        host._inflight_user_text = "hey jarvis, what"
        await self._run_scheduler(host)
        host.session.send_client_content.assert_not_awaited()
        self.assertIsNotNone(self.reg.get("reminder"))


if __name__ == "__main__":
    os.environ.setdefault("JARVIS_DATA_DIR", tempfile.mkdtemp())
    unittest.main()
