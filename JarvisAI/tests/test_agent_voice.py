"""Voice routing, action wiring and service-level authorization tests."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
JARVIS_DIR = ROOT_DIR / "JarvisAI"
for p in (str(ROOT_DIR), str(JARVIS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.events import AgentEvent
from agent.integration import AgentService, get_service, reset_service
from agent.models import StepKind, Task, TaskState, TaskStep
from agent.planner import Plan
from agent.settings import AgentSettings
from agent.store import TaskStore
from agent.voice import SpeechAnnouncer, VoiceCommandRouter, status_sentence


class VoiceCommandRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = VoiceCommandRouter()

    def test_stop_phrasings(self):
        for phrase in ("stop", "JARVIS, stop.", "stop the task", "cancel",
                       "jarvis abort", "halt everything", "stop working"):
            command = self.router.parse(phrase)
            self.assertIsNotNone(command, phrase)
            self.assertEqual(command.action, "stop", phrase)

    def test_pause_resume_status_report(self):
        cases = {
            "hold on": "pause",
            "JARVIS pause": "pause",
            "resume": "resume",
            "keep going": "resume",
            "what are you doing": "status",
            "task status": "status",
            "what did you find": "report",
            "final report": "report",
        }
        for phrase, action in cases.items():
            command = self.router.parse(phrase)
            self.assertIsNotNone(command, phrase)
            self.assertEqual(command.action, action, phrase)

    def test_multi_step_objective_is_recognised(self):
        text = ("inspect my project, fix the errors, finish the requested UI "
                "upgrade, run all relevant tests, and continue working until the "
                "task is completed")
        command = self.router.parse(text)
        self.assertIsNotNone(command)
        self.assertEqual(command.action, "run")
        self.assertIn("inspect my project", command.objective)
        self.assertTrue(any("completed" in item.casefold() for item in command.criteria))
        self.assertTrue(any("tests" in item.casefold() for item in command.criteria))

    def test_small_talk_is_not_hijacked(self):
        for phrase in ("what's the weather like tomorrow",
                       "play some music", "tell me a joke",
                       "set a timer for five minutes"):
            self.assertIsNone(self.router.parse(phrase), phrase)

    def test_objective_detection(self):
        self.assertFalse(VoiceCommandRouter.looks_like_objective("hello there"))
        self.assertFalse(VoiceCommandRouter.looks_like_objective("run"))
        self.assertTrue(VoiceCommandRouter.looks_like_objective(
            "review the repository and run the tests"
        ))


class SpeechAnnouncerTests(unittest.TestCase):
    def test_speaks_milestones_and_ignores_step_chatter(self):
        spoken: list[str] = []
        clock = [100.0]
        announcer = SpeechAnnouncer(spoken.append, min_interval_s=5.0,
                                    clock=lambda: clock[0])
        self.assertIsNone(announcer.announce(AgentEvent(kind="step_done",
                                                        message="step")))
        self.assertIsNotNone(announcer.announce(AgentEvent(kind="started")))
        clock[0] += 1
        self.assertIsNone(announcer.announce(AgentEvent(kind="planned")))  # throttled
        clock[0] += 10
        self.assertIsNotNone(announcer.announce(AgentEvent(kind="planned")))
        self.assertEqual(len(spoken), 2)

    def test_finished_always_speaks_even_inside_throttle_window(self):
        spoken: list[str] = []
        announcer = SpeechAnnouncer(spoken.append, min_interval_s=60.0,
                                    clock=lambda: 0.0)
        announcer.announce(AgentEvent(kind="started"))
        result = announcer.announce(AgentEvent(
            kind="finished", state=TaskState.COMPLETED,
            data={"report": {"failed": [], "blocked": []}},
        ))
        self.assertIn("Task complete", result or "")
        self.assertEqual(len(spoken), 2)

    def test_blocked_and_failed_are_explained(self):
        spoken: list[str] = []
        announcer = SpeechAnnouncer(spoken.append, min_interval_s=0.0,
                                    clock=lambda: 0.0)
        announcer.announce(AgentEvent(kind="blocked", message="needs a Gemini API key"))
        announcer.announce(AgentEvent(
            kind="finished", state=TaskState.FAILED,
            data={"report": {"failed": ["a"], "blocked": []}},
        ))
        self.assertIn("Gemini", spoken[0])
        self.assertIn("failed", spoken[1])

    def test_disabled_or_unbound_announcer_is_silent(self):
        self.assertIsNone(SpeechAnnouncer(None).announce(AgentEvent(kind="started")))
        self.assertIsNone(SpeechAnnouncer(lambda text: None, enabled=False)
                          .announce(AgentEvent(kind="started")))

    def test_speak_errors_do_not_escape(self):
        def broken(_text):
            raise RuntimeError("speaker unplugged")

        announcer = SpeechAnnouncer(broken, min_interval_s=0.0, clock=lambda: 0.0)
        self.assertIsNone(announcer.announce(AgentEvent(kind="started")))

    def test_status_sentence(self):
        self.assertEqual(status_sentence(None), "No task is running.")
        task = Task(objective="Upgrade the UI")
        task.set_plan([TaskStep(title="inspect"), TaskStep(title="fix")])
        task.transition(TaskState.PLANNING)
        task.transition(TaskState.RUNNING)
        sentence = status_sentence(task)
        self.assertIn("WORKING", sentence)
        self.assertIn("inspect", sentence)


class SecurityTierTests(unittest.TestCase):
    def test_stop_is_never_gated_and_run_is_dangerous(self):
        from core.security import TIER_DANGEROUS, TIER_SAFE, TIER_SENSITIVE, tier_for

        self.assertEqual(tier_for("autonomous_task", {"action": "stop"}), TIER_SAFE)
        self.assertEqual(tier_for("autonomous_task", {"action": "status"}), TIER_SENSITIVE)
        self.assertEqual(tier_for("autonomous_task", {"action": "pause"}), TIER_SENSITIVE)
        self.assertEqual(tier_for("autonomous_task", {"action": "run"}), TIER_DANGEROUS)
        # Unknown operations fail closed.
        self.assertEqual(tier_for("autonomous_task", {"action": "surprise"}),
                         TIER_DANGEROUS)


class ActionRegistrationTests(unittest.TestCase):
    def test_action_is_discovered_and_valid(self):
        from core.action_loader import discover_actions

        registry = discover_actions(JARVIS_DIR / "actions",
                                    logger=lambda message: None)
        self.assertTrue(registry.has("autonomous_task"))
        declarations = {item["name"]: item for item in registry.get_tool_declarations()}
        self.assertIn("autonomous_task", declarations)
        params = declarations["autonomous_task"]["parameters"]
        self.assertIn("run", params["properties"]["action"]["enum"])
        self.assertEqual(declarations["autonomous_task"].get("behavior"), "NON_BLOCKING")
        self.assertEqual(registry.scheduling("autonomous_task"), "SILENT")


class StubPlanner:
    def plan(self, objective, criteria=None):
        return Plan(
            steps=[
                TaskStep(title="note one", kind=StepKind.NOTE, detail="looked"),
                TaskStep(title="note two", kind=StepKind.NOTE, detail="thought"),
            ],
            criteria=["done"],
            source="stub",
        )


class AgentServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        store = TaskStore(Path(self._tmp.name))
        self.settings = AgentSettings(enabled=True, max_runtime_s=30.0, retry_budget=2)
        self.service = AgentService(
            settings=self.settings,
            workspace=ROOT_DIR,
            store=store,
            planner=StubPlanner(),
            ask_model=None,
            logger_=lambda message: None,
        )
        self.service._owner_authorized = lambda: True  # type: ignore[method-assign]
        self.service._privacy_locked = lambda: False  # type: ignore[method-assign]
        self.addCleanup(self.service.shutdown)

    def _wait_terminal(self, task, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not task.state.terminal:
            time.sleep(0.01)
        return task

    def test_start_completes_in_background_and_reports(self):
        task = self.service.start("do the work", source="test")
        self._wait_terminal(task)
        self.assertIs(task.state, TaskState.COMPLETED)
        self.assertIn("Task complete", self.service.report_text())
        self.assertIn("WORKING", self.service.status_sentence().upper() + " WORKING")

    def test_owner_check_is_required(self):
        self.service._owner_authorized = lambda: False  # type: ignore[method-assign]
        with self.assertRaises(PermissionError):
            self.service.start("do the work")
        reply = self.service.handle_tool({"action": "run", "objective": "x"})
        self.assertIn("Owner verification", reply)

    def test_privacy_lock_blocks_start(self):
        self.service._privacy_locked = lambda: True  # type: ignore[method-assign]
        with self.assertRaises(PermissionError):
            self.service.start("do the work")

    def test_disabled_autonomy_blocks_start(self):
        self.service.settings = AgentSettings(enabled=False)
        with self.assertRaises(PermissionError):
            self.service.start("do the work")

    def test_tool_facade_actions(self):
        self.assertIn("Tell me the objective", self.service.handle_tool({"action": "run"}))
        start = self.service.handle_tool({"action": "run", "objective": "tidy the repo"})
        self.assertIn("Starting an autonomous task", start)
        stop_reply = self.service.handle_tool({"action": "stop"}).casefold()
        self.assertTrue("stopping" in stop_reply or "no autonomous task" in stop_reply)

    def test_voice_commands_round_trip(self):
        self.assertIsNone(self.service.handle_voice("what's the weather"))
        stop_reply = (self.service.handle_voice("JARVIS, stop.") or "").casefold()
        # With nothing running the honest answer is "Nothing is running to stop."
        self.assertTrue("stopping" in stop_reply or "nothing is running" in stop_reply)
        self.assertIn("there is no task report",
                      (self.service.handle_voice("task report") or "").casefold())

    def test_status_payload_is_json_friendly(self):
        status = self.service.status()
        self.assertIn("settings", status)
        self.assertIn("capabilities", status)
        self.assertIsInstance(status["queued"], list)

    def test_screen_access_can_be_paused_by_owner(self):
        self.service.set_screen_paused(True)
        self.assertTrue(self.service.capture.paused)
        self.service.set_screen_paused(False)
        self.assertFalse(self.service.capture.paused)

    def test_singleton_can_be_replaced_for_tests(self):
        reset_service(self.service)
        self.assertIs(get_service(), self.service)
        reset_service(None)


class SettingsTests(unittest.TestCase):
    def test_defaults_and_env_overrides(self):
        settings = AgentSettings.load({})
        self.assertTrue(settings.enabled)
        self.assertFalse(settings.dry_run)
        with patch.dict("os.environ", {"JARVIS_AGENT_DRY_RUN": "1",
                                       "JARVIS_AGENT_MAX_RUNTIME": "120"}):
            dry = AgentSettings.load({})
        self.assertTrue(dry.dry_run)
        self.assertEqual(dry.max_runtime_s, 120.0)
        notes = dry.capability_notes()
        self.assertTrue(any("Dry-run" in note for note in notes))

    def test_config_values_and_bounds(self):
        # Ambient JARVIS_AGENT_* variables (JARVIS sets them when it spawns a
        # task) must not leak into this assertion.
        with patch.dict("os.environ", {"JARVIS_AGENT_MAX_RUNTIME": "",
                                       "JARVIS_AGENT_DRY_RUN": ""}):
            settings = AgentSettings.load({
                "autonomous_allow_desktop": False,
                "autonomous_max_runtime_s": 999999,
                "autonomous_retry_budget": 999,
            })
        self.assertFalse(settings.allow_desktop)
        self.assertEqual(settings.max_runtime_s, 14400.0)
        self.assertEqual(settings.retry_budget, 60)
        self.assertTrue(any("Desktop control" in note
                            for note in settings.capability_notes()))


if __name__ == "__main__":
    unittest.main()
