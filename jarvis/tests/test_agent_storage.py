"""Where autonomous tasks are stored: local by default, Supabase only by choice.

Regression for docs/research/JARVIS_SYSTEM_AUDIT.md B1: the service used to
default to the cloud-only store, so without Supabase configured every
``autonomous_task`` call failed. These tests build the service *without*
injecting a store, which is how the running app builds it.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jarvis.agent import storage
from jarvis.agent.cloud_store import CloudTaskStore
from jarvis.agent.integration import AgentService
from jarvis.agent.models import StepKind, TaskStep
from jarvis.agent.planner import Plan
from jarvis.agent.runner import TaskRunner
from jarvis.agent.settings import AgentSettings
from jarvis.agent.store import TaskStore

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_NO_CLOUD = {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": ""}


class _StubPlanner:
    def plan(self, objective, criteria=None):
        return Plan(steps=[TaskStep(title="note", kind=StepKind.NOTE, detail="looked")],
                    criteria=["done"], source="stub")


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.agent_dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"JARVIS_AGENT_DIR": str(self.agent_dir),
                                           "JARVIS_AGENT_STORAGE": "", **_NO_CLOUD})
        env.start()
        self.addCleanup(env.stop)

    def service(self, **settings) -> AgentService:
        svc = AgentService(
            settings=AgentSettings(enabled=True, max_runtime_s=30.0, retry_budget=1, **settings),
            workspace=ROOT_DIR, planner=_StubPlanner(), ask_model=None,
            logger_=lambda message: None,
        )
        svc._owner_authorized = lambda: True   # type: ignore[method-assign]
        svc._privacy_locked = lambda: False    # type: ignore[method-assign]
        self.addCleanup(svc.shutdown)
        return svc

    @staticmethod
    def wait_terminal(svc: AgentService, task_id: str, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = svc.store.load(task_id)
            if task is not None and task.state.terminal:
                return task
            time.sleep(0.02)
        return svc.store.load(task_id)


class SettingTests(unittest.TestCase):
    def test_default_is_local(self):
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_STORAGE": ""}):
            self.assertEqual(AgentSettings.load({}).task_storage, "local")

    def test_config_key_selects_cloud(self):
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_STORAGE": ""}):
            settings = AgentSettings.load({"autonomous_task_storage": "Cloud"})
        self.assertEqual(settings.task_storage, "cloud")

    def test_environment_wins_over_config(self):
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_STORAGE": "local"}):
            settings = AgentSettings.load({"autonomous_task_storage": "cloud"})
        self.assertEqual(settings.task_storage, "local")

    def test_unknown_value_falls_back_to_local_not_cloud(self):
        with mock.patch.dict(os.environ, {"JARVIS_AGENT_STORAGE": ""}):
            self.assertEqual(AgentSettings.load({"autonomous_task_storage": "s3"}).task_storage,
                             "local")

    def test_save_settings_normalises_the_choice(self):
        written = {}
        with mock.patch("jarvis.memory.config_manager.load_api_keys", return_value={"other": 1}), \
             mock.patch("jarvis.memory.config_manager.write_api_config", side_effect=written.update):
            from jarvis.agent.settings import save_settings
            save_settings({"autonomous_task_storage": "  CLOUD "})
        self.assertEqual(written, {"other": 1, "autonomous_task_storage": "cloud"})


class LocalDefaultTests(_Base):
    def test_service_without_supabase_runs_a_task_and_keeps_it_on_disk(self):
        svc = self.service()
        self.assertIsInstance(svc.store, TaskStore)
        self.assertEqual(svc.storage.kind, "local")
        reply = svc.handle_tool({"action": "run", "objective": "look at the project"})
        self.assertIn("Starting an autonomous task", reply)
        task_id = svc.runner.active_task.id if svc.runner.active_task else svc._last_task_id
        task = self.wait_terminal(svc, task_id)
        self.assertIsNotNone(task)
        self.assertTrue(task.state.terminal, task.state)
        self.assertTrue((self.agent_dir / "tasks" / f"{task_id}.json").is_file())
        self.assertIn(task_id, [row["id"] for row in svc.store.list_tasks()])

    def test_a_restarted_service_sees_the_unfinished_task(self):
        from jarvis.agent.models import Task
        pending = Task(objective="resume me after restart")
        pending.set_plan([TaskStep(title="note", kind=StepKind.NOTE, detail="later")])
        self.service().store.save(pending)         # saved by the first "run" of the app
        restarted = self.service()                  # a new service on the same data folder
        self.assertIn(pending.id, [t.id for t in restarted.store.unfinished()])
        self.assertIn("resume me after restart",
                      restarted.handle_tool({"action": "pending"}))

    def test_status_names_the_storage_without_a_path(self):
        svc = self.service()
        status = svc.status()
        self.assertEqual(status["storage"], {"kind": "local", "label": "local, on this PC",
                                             "problem": ""})
        self.assertNotIn(str(self.agent_dir), str(status["storage_backend"]))
        self.assertNotIn(os.sep + "tasks", str(status["storage_backend"]))
        self.assertEqual(svc.storage_sentence(), "Autonomous task storage: local, on this PC.")

    def test_a_bare_runner_also_defaults_to_local(self):
        self.assertIsInstance(TaskRunner(workspace=ROOT_DIR).store, TaskStore)


class CloudChoiceTests(_Base):
    def test_cloud_without_supabase_refuses_clearly_and_writes_nothing(self):
        svc = self.service(task_storage="cloud")
        self.assertIsInstance(svc.store, CloudTaskStore)
        reply = svc.handle_tool({"action": "run", "objective": "look at the project"})
        self.assertIn("set to Supabase cloud", reply)
        self.assertIn("SUPABASE_URL and SUPABASE_ANON_KEY are not set", reply)
        self.assertIn("switch task storage to local", reply)
        self.assertIsNone(svc.runner.active_task)
        self.assertFalse((self.agent_dir / "tasks").exists(), "cloud mode must not write locally")

    def test_cloud_status_and_list_report_the_reason(self):
        svc = self.service(task_storage="cloud")
        for action in ("status", "pending"):
            with self.subTest(action=action):
                self.assertIn("switch task storage to local", svc.handle_tool({"action": action}))
        self.assertEqual(svc.status()["storage"]["kind"], "cloud")

    def test_cloud_with_settings_present_uses_the_cloud_store_and_does_not_fall_back(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://example.invalid",
                                          "SUPABASE_ANON_KEY": "public-anon"}):
            svc = self.service(task_storage="cloud")
            self.assertEqual(svc.storage_problem(), "")
            with mock.patch("jarvis.agent.cloud_store.save_cloud_agent_task",
                            side_effect=RuntimeError("Personal memory request failed (URLError)")):
                reply = svc.handle_tool({"action": "run", "objective": "look at the project"})
        self.assertNotIn("Starting an autonomous task", reply)
        self.assertIn("Personal memory request failed", reply)
        self.assertFalse((self.agent_dir / "tasks").exists(), "an outage must not fall back to disk")


class RegistryDispatchTests(_Base):
    """The voice path: Gemini → live_tools → ActionRegistry.run → autonomous_task.

    Regression for a handler signature that read keyword fields while the registry
    passes ``parameters=``: every call, including ``run``, became ``status``.
    """

    def _registry(self):
        from jarvis.core.action_loader import discover_actions
        return discover_actions(ROOT_DIR / "jarvis" / "actions", logger=lambda message: None)

    def test_registry_passes_the_models_arguments_through(self):
        import jarvis.actions.autonomous_task as tool
        seen = {}

        class _Recorder:
            def attach_tool_dispatch(self, dispatch):
                seen["dispatch"] = dispatch

            def handle_tool(self, params, speak=None):
                seen.update(params)
                return "ok"

        args = {"action": "run", "objective": "fix the tests", "criteria": ["green"],
                "task_id": "t-1", "name": "nightly", "workflow_id": "w-1"}
        with mock.patch.object(tool, "get_service", return_value=_Recorder()):
            self.assertEqual(self._registry().run("autonomous_task", args, {}), "ok")
        self.assertEqual({key: seen[key] for key in args}, args)

    def test_keyword_callers_still_work(self):
        import jarvis.actions.autonomous_task as tool
        seen = {}

        class _Recorder:
            def handle_tool(self, params, speak=None):
                seen.update(params)
                return "ok"

        with mock.patch.object(tool, "get_service", return_value=_Recorder()):
            tool.autonomous_task(action="stop")
        self.assertEqual(seen["action"], "stop")

    def test_voice_path_starts_a_real_local_task(self):
        svc = self.service()
        with mock.patch("jarvis.actions.autonomous_task.get_service", return_value=svc):
            reply = self._registry().run("autonomous_task",
                                         {"action": "run", "objective": "look at the project"}, {})
        self.assertIn("Starting an autonomous task: look at the project", reply)
        task = self.wait_terminal(svc, svc._last_task_id)
        self.assertTrue(task is not None and task.state.terminal)
        self.assertTrue((self.agent_dir / "tasks" / f"{task.id}.json").is_file())


class ConfigurationProblemTests(unittest.TestCase):
    def test_names_each_missing_setting(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://x.invalid", "SUPABASE_ANON_KEY": ""}):
            self.assertEqual(storage.cloud_configuration_problem(), "SUPABASE_ANON_KEY is not set")
        with mock.patch.dict(os.environ, _NO_CLOUD):
            self.assertEqual(storage.cloud_configuration_problem(),
                             "SUPABASE_URL and SUPABASE_ANON_KEY are not set")
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://x.invalid",
                                          "SUPABASE_ANON_KEY": "k"}):
            self.assertEqual(storage.cloud_configuration_problem(), "")


class SelfCheckTests(_Base):
    def test_self_check_reports_storage_and_the_cloud_reason(self):
        from jarvis.actions import self_check
        for choice, expected in (("local", "Autonomous task storage: local, on this PC."),
                                 ("cloud", "SUPABASE_URL and SUPABASE_ANON_KEY are not set")):
            with self.subTest(choice=choice):
                svc = self.service(task_storage=choice)
                with mock.patch("jarvis.agent.integration.get_service", return_value=svc):
                    self.assertIn(expected, self_check._agent_line())


if __name__ == "__main__":
    unittest.main()
