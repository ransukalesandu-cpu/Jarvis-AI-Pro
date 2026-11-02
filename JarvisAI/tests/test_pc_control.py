"""Module 3: generic PC control tools, UI automation loop and routines."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
if str(JARVIS_DIR) not in sys.path:
    sys.path.insert(0, str(JARVIS_DIR))

from core import owner_store, pc_control as pc  # noqa: E402
from core.capture import Frame  # noqa: E402
from core.routines import steps_from_session  # noqa: E402
from core.ui_automation import automate  # noqa: E402

PY = sys.executable


class RunCommandTests(unittest.TestCase):
    def test_output_and_exit_code(self):
        res = pc.run_command("", argv=[PY, "-c", "import sys; print('hi'); "
                                                 "print('oops', file=sys.stderr); sys.exit(3)"])
        self.assertEqual(res.exit_code, 3)
        self.assertIn("hi", res.stdout)
        self.assertIn("oops", res.stderr)
        self.assertIn("Exit code 3", res.summary())

    def test_timeout_stops_the_process(self):
        res = pc.run_command("", argv=[PY, "-c", "import time; time.sleep(30)"], timeout=1)
        self.assertTrue(res.timed_out)
        self.assertLess(res.duration, 5)

    def test_cancel_event_stops_a_long_command_within_a_second(self):
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        started = time.monotonic()
        res = pc.run_command("", argv=[PY, "-c", "import time; time.sleep(30)"],
                             timeout=60, cancel_event=cancel)
        self.assertTrue(res.cancelled)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_windows_shell_argv(self):
        with patch.object(pc, "IS_WINDOWS", True):
            self.assertEqual(pc.shell_argv("dir", "cmd")[:2], ["cmd", "/d"])
            argv = pc.shell_argv("Get-Date")
            self.assertEqual(argv[0], "powershell")
            self.assertEqual(argv[-1], "Get-Date")


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        # Reading a file marks untrusted content for the turn; don't leak it.
        from core import security
        security.mark_user_turn_started()

    def test_write_read_list_copy_move_delete_search(self):
        from actions.pc_tools import files
        target = self.tmp / "notes" / "todo.txt"
        self.assertIn("Wrote", files({"action": "write", "path": str(target), "content": "buy milk"}))
        self.assertIn("buy milk", files({"action": "read", "path": str(target)}))
        self.assertIn("EXTERNAL CONTENT", files({"action": "read", "path": str(target)}))
        self.assertIn("todo.txt", files({"action": "list", "path": str(target.parent)}))
        files({"action": "copy", "path": str(target), "destination": str(self.tmp / "copy.txt")})
        (self.tmp / "archive").mkdir()
        files({"action": "move", "path": str(target), "destination": str(self.tmp / "archive")})
        self.assertTrue((self.tmp / "archive" / "todo.txt").exists())
        found = files({"action": "search", "pattern": "todo", "root": str(self.tmp)})
        self.assertIn(str(self.tmp / "archive" / "todo.txt"), found)
        by_text = files({"action": "search", "pattern": "*.txt", "contains": "milk",
                         "root": str(self.tmp)})
        self.assertIn("copy.txt", by_text)
        files({"action": "delete", "path": str(self.tmp / "archive")})
        self.assertFalse((self.tmp / "archive").exists())


class OpenTests(unittest.TestCase):
    def test_open_url_and_named_app_on_posix(self):
        with patch.object(pc, "IS_WINDOWS", False), \
             patch.object(pc.sys, "platform", "linux"), \
             patch.object(pc.subprocess, "Popen") as popen:
            pc.open_target("https://example.com")
            self.assertEqual(popen.call_args.args[0], ["xdg-open", "https://example.com"])
            pc.open_target("/tmp/x.txt", app="gedit")
            self.assertEqual(popen.call_args.args[0], ["gedit", "/tmp/x.txt"])

    def test_open_on_windows_uses_startfile_and_start(self):
        with patch.object(pc, "IS_WINDOWS", True), \
             patch.object(pc.os, "startfile", create=True) as startfile, \
             patch.object(pc.subprocess, "Popen") as popen:
            pc.open_target("steam://open/games")
            startfile.assert_called_once_with("steam://open/games")
            pc.open_target("https://example.com", app="msedge")
            self.assertEqual(popen.call_args.args[0][:5], ["cmd", "/c", "start", "", "msedge"])


class WingetAndSystemTests(unittest.TestCase):
    def test_install_by_id_and_name(self):
        argv = pc.winget_argv("install", "Mozilla.Firefox")
        self.assertEqual(argv[:5], ["winget", "install", "--id", "Mozilla.Firefox", "-e"])
        self.assertIn("--accept-package-agreements", argv)
        self.assertIn("--name", pc.winget_argv("install", "vlc media player"))
        self.assertIn("--all", pc.winget_argv("upgrade", "all"))

    def test_auto_location_uses_the_drive_with_most_free_space(self):
        with patch.object(pc, "best_drive", return_value={"drive": "D:\\", "free_gb": 400}), \
             patch.dict(pc.os.environ, {"SystemDrive": "C:"}):
            argv = pc.winget_argv("install", "Mozilla.Firefox", location="auto")
        loc = argv[argv.index("--location") + 1]
        self.assertTrue(loc.startswith("D:"))
        self.assertIn("Mozilla.Firefox", loc)
        with patch.object(pc, "best_drive", return_value={"drive": "C:\\", "free_gb": 400}), \
             patch.dict(pc.os.environ, {"SystemDrive": "C:"}):
            self.assertNotIn("--location", pc.winget_argv("install", "X.Y", location="auto"))

    def test_system_info_reports_drives_and_memory(self):
        from actions.pc_tools import system_info
        data = json.loads(system_info({"what": "all"}))
        self.assertIn("drives", data)
        self.assertIn("most_free_drive", data)
        self.assertGreater(data["memory"]["total_gb"], 0)
        procs = json.loads(system_info({"what": "processes", "top": 3}))["processes"]
        self.assertLessEqual(len(procs), 3)


class _FakeDriver:
    def __init__(self):
        self.done = []

    def perform(self, step, frame):
        self.done.append(step["action"])
        return ""


def _frame(_window=""):
    return Frame(jpeg=b"x", width=800, height=600, scale=2.0, left=10, top=20)


class UiAutomationTests(unittest.TestCase):
    def test_loop_until_done(self):
        script = iter([{"action": "click", "x": 100, "y": 50, "reason": "open menu"},
                       {"action": "type", "text": "hello"},
                       {"action": "done", "reason": "saved"}])
        driver = _FakeDriver()
        res = automate("save a note", decide=lambda *_: next(script), capture=_frame,
                       driver=driver, settle=0)
        self.assertTrue(res.success)
        self.assertEqual(driver.done, ["click", "type"])

    def test_step_limit_and_cancel(self):
        driver = _FakeDriver()
        res = automate("loop", decide=lambda *_: {"action": "wait"}, capture=_frame,
                       driver=driver, max_steps=3, settle=0)
        self.assertFalse(res.success)
        self.assertEqual(len(driver.done), 3)
        cancel = threading.Event()
        cancel.set()
        res = automate("x", decide=lambda *_: {"action": "wait"}, capture=_frame,
                       driver=driver, cancel_event=cancel, settle=0)
        self.assertIn("Stopped on request", res.message)

    def test_frame_maps_coordinates_back_to_the_screen(self):
        self.assertEqual(_frame().to_screen(100, 50), (210, 120))


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "owner.db"
        owner_store.reset_owner_store_for_tests(owner_store.OwnerStore(self.db))

    def tearDown(self):
        owner_store.reset_owner_store_for_tests(None)

    def test_steps_from_session_keep_only_successful_state_changes(self):
        calls = [{"tool": "open", "args": {"target": "https://mail.com"}, "status": "ok", "risk": "write"},
                 {"tool": "system_info", "args": {}, "status": "ok", "risk": "read"},
                 {"tool": "open", "args": {"target": "x"}, "status": "error", "risk": "write"},
                 {"tool": "routine", "args": {}, "status": "ok", "risk": "write"}]
        self.assertEqual(steps_from_session(calls), [{"tool": "open", "args": {"target": "https://mail.com"}}])

    def test_save_from_session_then_replay_after_restart(self):
        from actions import routines as routine_action
        routine_action._session_marker["index"] = 0
        calls = [{"tool": "open", "args": {"targets": ["code", "https://github.com"]},
                  "status": "ok", "risk": "write"},
                 {"tool": "run_command", "args": {"command": "echo hi"}, "status": "ok",
                  "risk": "destructive"}]
        out = routine_action.routine({"action": "save", "name": "Work Mode"}, session_calls=calls)
        self.assertIn("2 step", out)
        # A new store object on the same file stands in for a restart.
        owner_store.reset_owner_store_for_tests(owner_store.OwnerStore(self.db))
        ran = []
        out = routine_action.routine({"action": "run", "name": "work mode"},
                                     dispatch=lambda tool, args: ran.append((tool, args)) or "ok")
        self.assertEqual([t for t, _ in ran], ["open", "run_command"])
        self.assertIn("Ran routine 'work mode'", out)


class DispatchFromThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_tool_sync_runs_through_the_registry(self):
        import asyncio
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import live_replay
        host = live_replay.build_host()
        with patch("core.security.guard", side_effect=lambda _n, _a, run: run()), \
             patch("core.action_log.log_path", return_value=Path(tempfile.mkdtemp()) / "a.jsonl"):
            result = await asyncio.to_thread(host._dispatch_tool_sync, "system_info",
                                             {"what": "memory"})
        self.assertIn("total_gb", result)


if __name__ == "__main__":
    unittest.main()
