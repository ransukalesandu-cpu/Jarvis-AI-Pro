"""Lifecycle hooks: python + owner-folder script hooks, guard rails, wiring."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.core import events, hooks
from jarvis.core.hooks import HookRegistry


def _script(root: Path, event: str, name: str, body: str) -> Path:
    folder = root / event
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


class HooksBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hooks"
        self.reg = HookRegistry(self.root)
        self.addCleanup(self.tmp.cleanup)
        events.reset_for_tests()
        self.addCleanup(events.reset_for_tests)


class PythonHookTests(HooksBase):
    def test_handler_gets_event_and_payload_copy(self):
        seen = []
        self.reg.register("task_finished", lambda e, p: seen.append((e, p)), "a")
        self.reg.run_event("task_finished", {"task_id": "t1"})
        self.assertEqual(seen, [("task_finished", {"task_id": "t1"})])

    def test_unknown_event_and_non_callable_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.register("nope", lambda e, p: None)
        with self.assertRaises(ValueError):
            self.reg.register("startup", "not callable")

    def test_exception_is_isolated_and_reported(self):
        def boom(e, p):
            raise RuntimeError("bad")
        ran = []
        self.reg.register("startup", boom, "boom")
        self.reg.register("startup", lambda e, p: ran.append(1), "ok")
        results = self.reg.run_event("startup", {})
        self.assertEqual([(n, ok) for n, ok, _ in results], [("py:boom", False), ("py:ok", True)])
        self.assertIn("RuntimeError: bad", results[0][2])
        self.assertEqual(ran, [1])

    def test_timeout(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.reg.register("startup", lambda e, p: gate.wait(5), "slow")
        with patch.object(hooks, "PY_TIMEOUT", 0.1):
            (name, ok, detail), = self.reg.run_event("startup", {})
        self.assertFalse(ok)
        self.assertIn("timed out", detail)

    def test_three_failures_switch_off_and_notify(self):
        messages = []
        self.reg.notify = messages.append
        calls = []

        def boom(e, p):
            calls.append(1)
            raise RuntimeError("bad")
        self.reg.register("startup", boom, "boom")
        for _ in range(5):
            self.reg.run_event("startup", {})
        self.assertEqual(len(calls), 3)
        self.assertTrue(self.reg.is_off("py:boom"))
        self.assertEqual(len(messages), 1)
        self.assertIn("switched off", messages[0])
        self.reg.reset("py:boom")
        self.reg.run_event("startup", {})
        self.assertEqual(len(calls), 4)

    def test_success_resets_failure_count(self):
        state = {"fail": True}

        def flaky(e, p):
            if state["fail"]:
                raise RuntimeError("x")
        self.reg.register("startup", flaky, "flaky")
        self.reg.run_event("startup", {})
        self.reg.run_event("startup", {})
        state["fail"] = False
        self.reg.run_event("startup", {})
        state["fail"] = True
        self.reg.run_event("startup", {})
        self.reg.run_event("startup", {})
        self.assertFalse(self.reg.is_off("py:flaky"))


class ScriptHookTests(HooksBase):
    def test_python_script_receives_json_on_stdin(self):
        out = self.root / "out.json"
        _script(self.root, "task_finished", "save.py", f"""
            import json, sys
            data = json.load(sys.stdin)
            open({str(out)!r}, "w").write(json.dumps(data))
        """)
        (name, ok, detail), = self.reg.run_event("task_finished", {"task_id": "t9"})
        self.assertTrue(ok, detail)
        saved = json.loads(out.read_text())
        self.assertEqual((saved["event"], saved["payload"]), ("task_finished", {"task_id": "t9"}))

    def test_environment_is_minimal_no_secrets(self):
        out = self.root / "env.json"
        _script(self.root, "startup", "env.py", f"""
            import json, os
            open({str(out)!r}, "w").write(json.dumps(sorted(os.environ)))
        """)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret", "SUPABASE_SERVICE_KEY": "s2"}):
            (_, ok, detail), = self.reg.run_event("startup", {})
        self.assertTrue(ok, detail)
        names = json.loads(out.read_text())
        self.assertNotIn("GEMINI_API_KEY", names)
        self.assertNotIn("SUPABASE_SERVICE_KEY", names)
        self.assertIn("JARVIS_HOOK_EVENT", names)

    def test_nonzero_exit_is_failure_with_output(self):
        _script(self.root, "startup", "bad.py", """
            import sys
            print("oops"); sys.exit(3)
        """)
        (_, ok, detail), = self.reg.run_event("startup", {})
        self.assertFalse(ok)
        self.assertIn("exit 3", detail)
        self.assertIn("oops", detail)

    def test_script_timeout(self):
        _script(self.root, "startup", "slow.py", "import time; time.sleep(5)")
        with patch.object(hooks, "SCRIPT_TIMEOUT", 0.5):
            (_, ok, detail), = self.reg.run_event("startup", {})
        self.assertFalse(ok)
        self.assertIn("timed out", detail)

    def test_ignored_files(self):
        _script(self.root, "startup", "_helper.py", "pass")
        _script(self.root, "startup", ".hidden.py", "pass")
        _script(self.root, "startup", "notes.txt", "pass")
        _script(self.root, "startup", "real.py", "pass")
        self.assertEqual([p.name for p in self.reg.script_hooks("startup")], ["real.py"])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinks_are_ignored(self):
        outside = Path(self.tmp.name) / "outside.py"
        outside.write_text("print('x')", encoding="utf-8")
        folder = self.root / "startup"
        folder.mkdir(parents=True)
        (folder / "link.py").symlink_to(outside)
        self.assertEqual(self.reg.script_hooks("startup"), [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinked_event_folder_is_ignored(self):
        real = Path(self.tmp.name) / "elsewhere"
        real.mkdir()
        (real / "x.py").write_text("print('x')", encoding="utf-8")
        self.root.mkdir(parents=True)
        (self.root / "startup").symlink_to(real, target_is_directory=True)
        self.assertEqual(self.reg.script_hooks("startup"), [])

    def test_missing_folder_is_fine(self):
        self.assertEqual(self.reg.run_event("startup", {}), [])

    def test_repo_and_other_paths_are_never_scanned(self):
        # Only <user data>/hooks/<event>; a hook file elsewhere (e.g. next to code) is not run.
        stray = Path(self.tmp.name) / "startup"
        stray.mkdir()
        (stray / "evil.py").write_text("open('pwned','w')", encoding="utf-8")
        self.assertEqual(self.reg.script_hooks("startup"), [])

    def test_ledger_callback_records_each_run(self):
        rows = []
        self.reg.audit = lambda key, detail: rows.append((key, detail))
        _script(self.root, "startup", "a.py", "pass")
        self.reg.register("startup", lambda e, p: None, "p")
        self.reg.run_event("startup", {})
        self.assertEqual([k for k, _ in rows], ["py:p", "script:startup/a.py"])

    def test_three_script_failures_switch_it_off(self):
        marker = self.root / "count.txt"
        _script(self.root, "startup", "bad.py", f"""
            open({str(marker)!r}, "a").write("x")
            raise SystemExit(1)
        """)
        for _ in range(5):
            self.reg.run_event("startup", {})
        self.assertEqual(marker.read_text(), "xxx")
        self.assertTrue(self.reg.is_off("script:startup/bad.py"))


class EmitTests(HooksBase):
    def test_emit_is_async_and_wait_drains(self):
        done = []
        self.reg.register("startup", lambda e, p: (time.sleep(0.2), done.append(1)), "s")
        t0 = time.monotonic()
        self.reg.emit("startup", {})
        self.assertLess(time.monotonic() - t0, 0.15)
        self.assertEqual(done, [])
        self.reg.emit("startup", {}, wait=3.0)
        self.assertEqual(len(done), 2)

    def test_emit_without_hooks_does_nothing_and_unknown_event_ignored(self):
        self.reg.emit("startup", {})
        self.reg.emit("not_an_event", {})
        self.assertIsNone(self.reg._worker)

    def test_disable_switch(self):
        seen = []
        self.reg.register("startup", lambda e, p: seen.append(1), "s")
        with patch.dict(os.environ, {"JARVIS_DISABLE_HOOKS": "1"}):
            self.reg.emit("startup", {}, wait=1.0)
        self.assertEqual(seen, [])

    def test_event_is_forwarded_to_owner_rules_bus(self):
        heard = []
        events.subscribe(lambda source, payload: heard.append((source, payload)))
        with patch("jarvis.core.owner_store.get_owner_store", side_effect=RuntimeError("no store")):
            self.reg.emit("privacy_lock", {"why": "test"})
        self.assertEqual(heard, [("privacy_lock", {"why": "test"})])

    def test_full_queue_drops_oldest_not_newest(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        seen = []
        self.reg.register("startup", lambda e, p: (gate.wait(5), seen.append(p["n"])), "s")
        with patch.object(hooks, "QUEUE_LIMIT", 3):
            self.reg._queue = hooks.queue.Queue(maxsize=3)
            for n in range(8):
                self.reg.emit("startup", {"n": n})
            gate.set()
            self.reg.emit("startup", {"n": 99}, wait=5.0)
        self.assertIn(99, seen)
        self.assertLess(len(seen), 9)


class WiringTests(unittest.TestCase):
    def test_actions_can_expose_HOOKS(self):
        from jarvis.core.action_loader import discover_actions
        with tempfile.TemporaryDirectory() as tmp:
            actions = Path(tmp) / "actions"
            actions.mkdir()
            (actions / "demo_hook.py").write_text(textwrap.dedent("""
                def on_done(event, payload):
                    pass
                HOOKS = [{"event": "task_finished", "handler": on_done, "name": "demo"}]
                TOOL = {"name": "demo_hook", "description": "d",
                        "parameters": {"type": "OBJECT", "properties": {}}, "handler": lambda p, **k: "ok"}
            """), encoding="utf-8")
            reg = HookRegistry(Path(tmp) / "hooks")
            hooks.reset_for_tests(reg)
            try:
                discover_actions(actions, logger=lambda m: None)
                self.assertEqual([h["name"] for h in reg.python_hooks("task_finished")], ["demo"])
            finally:
                hooks.reset_for_tests(None)
                sys.modules.pop("jarvis.actions.demo_hook", None)

    def test_bad_HOOKS_row_is_rejected_not_fatal(self):
        from jarvis.core.action_loader import _collect_hooks
        logs = []
        module = type("M", (), {"HOOKS": [{"event": "nope", "handler": print}]})
        reg = HookRegistry(Path(tempfile.gettempdir()) / "none")
        hooks.reset_for_tests(reg)
        try:
            _collect_hooks(module, "x.py", logs.append)
        finally:
            hooks.reset_for_tests(None)
        self.assertTrue(any("rejected" in m for m in logs))

    def test_module_emit_never_raises(self):
        with patch.object(hooks, "get_hook_registry", side_effect=RuntimeError("boom")):
            hooks.emit("startup", {})


if __name__ == "__main__":
    unittest.main()
