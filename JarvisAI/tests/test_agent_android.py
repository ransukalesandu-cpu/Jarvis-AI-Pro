"""Phase 2 Module D: ADB layer (fake adb), tool host, and the agent protocol end to end."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

JARVIS_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (JARVIS_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from aiohttp.test_utils import TestServer  # noqa: E402

from laptop_agent.devices.android import (  # noqa: E402
    Adb, AdbError, AndroidDevice, AndroidManager, AndroidTarget, parse_devices,
)

TABLET = "TAB123"
PHONE = "192.168.1.50:5555"


class FakeAdb:
    def __init__(self, devices=None, reachable=()):
        self.dir = Path(tempfile.mkdtemp())
        self.state = self.dir / "state.json"
        self.state.write_text(json.dumps({
            "devices": devices if devices is not None else {
                TABLET: {"state": "device", "usb": True, "model": "Greentel_T10", "android": "11",
                         "packages": ["com.android.chrome", "com.google.android.youtube"]}},
            "reachable": list(reachable),
            "phone_packages": ["com.google.android.youtube", "com.whatsapp", "org.mozilla.firefox"],
        }))
        if os.name == "nt":
            self.path = str(self.dir / "adb.cmd")
            Path(self.path).write_text(f'@"{sys.executable}" "{TESTS_DIR / "fake_adb.py"}" %*\r\n')
        else:
            self.path = str(self.dir / "adb")
            Path(self.path).write_text(f'#!/bin/sh\nexec "{sys.executable}" "{TESTS_DIR / "fake_adb.py"}" "$@"\n')
            os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)
        self.env = patch.dict(os.environ, {"FAKE_ADB_STATE": str(self.state), "JARVIS_ADB": self.path})
        self.env.start()

    def stop(self):
        self.env.stop()

    def log(self):
        return json.loads(self.state.read_text())["log"]

    def shell_lines(self, serial=None):
        return [e["args"][1] for e in self.log() if e["args"][:1] == ["shell"]
                and (serial is None or e["serial"] == serial)]


class AdbLayerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeAdb(reachable=[PHONE])
        self.adb = Adb(self.fake.path)
        self.tablet = AndroidDevice(AndroidTarget("tablet", serial="usb", reverse_ports=[8765]), self.adb)
        self.phone = AndroidDevice(AndroidTarget("phone", address=PHONE), self.adb)

    def tearDown(self):
        self.fake.stop()

    def test_parse_devices(self):
        rows = parse_devices("List of devices attached\nABC\tdevice usb:1-1 model:T\n10.0.0.2:5555\toffline\n")
        self.assertEqual([(r["serial"], r["state"], r["usb"]) for r in rows],
                         [("ABC", "device", True), ("10.0.0.2:5555", "offline", False)])

    def test_usb_tablet_resolves_and_offline_phone_is_reported(self):
        self.assertEqual(self.tablet.serial(), TABLET)
        with self.assertRaisesRegex(AdbError, "phone is not connected"):
            self.phone.serial()

    def test_manager_connects_wireless_phone_and_applies_reverse_once(self):
        mgr = AndroidManager([self.tablet.target, self.phone.target], self.adb)
        status = mgr.poll()
        self.assertTrue(status["phone"]["online"])
        self.assertEqual(status["phone"]["transport"], "wifi")
        self.assertEqual(status["tablet"]["transport"], "usb")
        mgr.poll()
        reverses = [e for e in self.fake.log() if e["args"][:1] == ["reverse"]]
        self.assertEqual(len(reverses), 1)                 # re-applied only when it reappears
        self.assertEqual(reverses[0]["args"], ["reverse", "tcp:8765", "tcp:8765"])

    def test_actions_issue_the_right_adb_commands(self):
        self.assertIn("youtube", self.tablet.open_app("YouTube"))
        self.tablet.open_url("https://example.com")
        self.tablet.type_text("hello world & more")
        self.tablet.press_key("volume_up")
        self.tablet.tap(10, 20)
        lines = self.fake.shell_lines(TABLET)
        self.assertIn("monkey -p com.google.android.youtube -c android.intent.category.LAUNCHER 1", lines)
        self.assertIn("am start -a android.intent.action.VIEW -d https://example.com", lines)
        self.assertIn("input text hello%sworld%s\\&%smore", lines)
        self.assertIn("input keyevent KEYCODE_VOLUME_UP", lines)
        self.assertIn("input tap 10 20", lines)
        with self.assertRaisesRegex(AdbError, "No app matching"):
            self.tablet.open_app("nonexistent thing")

    def test_info_and_screenshot(self):
        info = self.tablet.info()
        self.assertEqual((info["android"], info["battery_percent"], info["ram_gb"]), ("11", 81, 3.8))
        self.assertTrue(info["charging"])
        self.assertTrue(self.tablet.screenshot_png().startswith(b"\x89PNG"))

    def test_missing_adb_is_a_spoken_error(self):
        with patch("laptop_agent.devices.android.find_adb", return_value=None), \
             self.assertRaisesRegex(AdbError, "adb is not installed"):
            Adb().run("devices")


class ToolHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from laptop_agent.android_tools import AndroidTools
        from laptop_agent.tool_host import ToolHost
        cls.fake = FakeAdb(reachable=[PHONE])
        mgr = AndroidManager([], Adb(cls.fake.path))
        mgr.configure([{"name": "tablet", "serial": "usb"}, {"name": "phone", "address": PHONE}])
        cls.host = ToolHost(AndroidTools(mgr), state_dir=Path(tempfile.mkdtemp()))
        cls.decls = cls.host.load_declarations()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def test_announces_laptop_tools_but_not_hub_tools(self):
        names = {r["declaration"]["name"] for r in self.decls}
        for laptop_tool in ("run_command", "files", "see_screen", "open_app", "device_shell", "push_file"):
            self.assertIn(laptop_tool, names)
        for hub_tool in ("routine", "facts", "proactive_triggers", "show_recent_actions"):
            self.assertNotIn(hub_tool, names)

    def test_shared_names_are_merged(self):
        open_app = [r for r in self.decls if r["declaration"]["name"] == "open_app"][0]["declaration"]
        props = open_app["parameters"]["properties"]
        self.assertIn("package", props)
        self.assertIn("device=tablet or phone", open_app["description"])

    def test_laptop_tools_behave_exactly_as_in_phase_1(self):
        from actions.pc_tools import files
        folder = tempfile.mkdtemp()
        Path(folder, "a.txt").write_text("1")
        direct = files({"action": "list", "path": folder})
        via_agent = self.host.run("files", {"action": "list", "path": folder}, "laptop", {})
        self.assertEqual(via_agent, direct)

    def test_routes_by_device(self):
        out = self.host.run("open_app", {"app_name": "youtube"}, "tablet", {})
        self.assertIn("Opened com.google.android.youtube on the tablet", out)
        self.assertIn("runs on the laptop", self.host.run("run_command", {"command": "x"}, "tablet", {}))
        with patch("core.pc_control.run_command") as rc:
            rc.return_value = SimpleNamespace(summary=lambda: "Exit code 0.")
            out = self.host.run("device_shell", {"command": "echo hi"}, "laptop", {"cancel_event": None})
        self.assertIn("Exit code 0", out)


class AgentProtocolTests(unittest.IsolatedAsyncioTestCase):
    """A real hub and a real AgentClient over WebSockets, with fake adb."""

    async def asyncSetUp(self):
        from hub.config import load_config
        from hub.remote_tools import RemoteToolRegistry
        from hub.server import Hub
        from laptop_agent.android_tools import AndroidTools
        from laptop_agent.client import AgentClient
        from laptop_agent.config import AgentConfig
        from laptop_agent.tool_host import ToolHost

        self.fake = FakeAdb(reachable=[PHONE])
        state = tempfile.mkdtemp()
        with patch.dict("os.environ", {"JARVIS_HUB_STATE": state, "JARVIS_HUB_LIVE": "0"}):
            cfg = load_config(heartbeat_seconds=0.5)
        Path(cfg.devices_path).write_text(json.dumps({"devices": [
            {"name": "laptop", "kind": "agent"},
            {"name": "tablet", "kind": "android", "client": True, "adb": {"serial": "usb", "via": "laptop"}},
            {"name": "phone", "kind": "android", "client": True, "adb": {"address": PHONE, "via": "laptop"}},
        ]}))
        self.hub = Hub(cfg)
        self.hub.loop = asyncio.get_running_loop()
        self.shown = []
        self.hub.live = SimpleNamespace(_queue_vision=lambda *a: self.shown.append(a),
                                        speak=lambda t: None, ui=SimpleNamespace(write_log=lambda t: None))
        self.remote = RemoteToolRegistry(self.hub)
        self.server = TestServer(self.hub.app)
        await self.server.start_server()
        token, _ = self.hub.tokens.redeem(self.hub.tokens.create_code("laptop", "agent").code)
        mgr = AndroidManager([], Adb(self.fake.path))
        host = ToolHost(AndroidTools(mgr), state_dir=Path(tempfile.mkdtemp()))
        host.load_declarations()
        acfg = AgentConfig(hub_url=f"ws://127.0.0.1:{self.server.port}", token=token,
                           path=Path(tempfile.mkdtemp()) / "agent.json")
        with patch("laptop_agent.client.HEARTBEAT", 0.3):
            self.agent = AgentClient(acfg, host, mgr)
            self.agent_task = asyncio.create_task(self.agent.run())
            await self._until(lambda: self.remote.has("device_info") and self.hub.registry.online("phone", "adb"))

    async def asyncTearDown(self):
        from core import gemini
        gemini.set_remote_call(None)       # the agent routes Gemini through the hub
        self.agent.stop_event.set()
        self.agent_task.cancel()
        await asyncio.gather(self.agent_task, return_exceptions=True)
        await self.server.close()
        self.fake.stop()

    async def _until(self, pred, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.05)
        self.fail("condition not reached")

    async def _run(self, tool, args, device, ctx=None):
        return await asyncio.to_thread(self.remote.run, tool, args, {"device": device, **(ctx or {})})

    async def test_open_app_on_phone_and_tablet_and_type_text(self):
        self.assertIn("on the phone", await self._run("open_app", {"app_name": "whatsapp"}, "phone"))
        self.assertIn("on the tablet", await self._run("open_app", {"app_name": "youtube"}, "tablet"))
        self.assertIn("Typed", await self._run("type_text", {"text": "hi"}, "phone"))
        self.assertIn("monkey -p com.whatsapp -c android.intent.category.LAUNCHER 1",
                      self.fake.shell_lines(PHONE))

    async def test_screenshot_of_another_device_is_shown_to_gemini(self):
        out = await self._run("device_screenshot", {"question": "what is on my phone?"}, "phone")
        self.assertIn("Describe it from the image", out)
        await self._until(lambda: self.shown)
        data, mime, question, source = self.shown[0]
        self.assertEqual((mime, question, source), ("image/jpeg", "what is on my phone?", "phone screen"))
        self.assertTrue(data.startswith(b"\xff\xd8"))

    async def test_send_a_laptop_file_to_the_phone(self):
        f = Path(tempfile.mkdtemp()) / "report.pdf"
        f.write_text("x")
        out = await self._run("push_file", {"path": str(f)}, "phone")
        self.assertIn("report.pdf", out)
        pushes = [e for e in self.fake.log() if e["args"][:1] == ["push"]]
        self.assertEqual(pushes[-1]["args"][2], "/sdcard/Download/report.pdf")

    async def test_unknown_and_offline_devices_give_spoken_errors(self):
        self.assertIn("don't know a device called 'fridge'", await self._run("device_info", {}, "fridge"))
        state = json.loads(self.fake.state.read_text())
        state["devices"].pop(PHONE)
        state["reachable"] = []
        self.fake.state.write_text(json.dumps(state))
        await self._until(lambda: not self.hub.registry.online("phone", "adb"))
        self.assertIn("not connected", await self._run("device_info", {}, "phone"))

    async def test_list_devices_shows_adb_presence(self):
        text = self.hub.tools.run("list_devices", {})
        self.assertIn("phone is online", text)
        self.assertIn("adb", text)

    async def test_agent_drop_mid_call_fails_cleanly(self):
        started = threading.Event()

        def slow(name, args, device, ctx):
            started.set()
            time.sleep(3)
            return "late"
        self.agent.host.run = slow
        task = asyncio.create_task(self._run("device_info", {}, "phone"))
        await asyncio.to_thread(started.wait, 5)
        await self.hub.agents.close_device("laptop", 4408, "test drop")
        result = await asyncio.wait_for(task, 5)
        self.assertIn("disconnected while running device info", result)

    async def test_stop_word_cancels_a_remote_call(self):
        seen = threading.Event()

        def waits(name, args, device, ctx):
            ctx["cancel_event"].wait(10)
            seen.set()
            return "stopped on the laptop"
        self.agent.host.run = waits
        cancel = threading.Event()
        task = asyncio.create_task(self._run("device_info", {}, "phone", {"cancel_event": cancel}))
        await asyncio.sleep(0.3)
        cancel.set()
        result = await asyncio.wait_for(task, 5)
        self.assertEqual(result, "stopped on the laptop")
        self.assertTrue(seen.is_set())

    async def test_agent_tools_ask_gemini_through_the_hub(self):
        from core import gemini
        with patch.object(gemini, "_REMOTE_CALL", None), \
             patch("core.gemini.call", wraps=None) as hub_call:
            hub_call.return_value = SimpleNamespace(text='{"ok": true}')
            text = await asyncio.to_thread(self.agent.gemini_call, ["describe", {"inline_data": {
                "mime_type": "image/jpeg", "data": b"\xff\xd8"}}], "fast", None, 5000)
        self.assertEqual(text, '{"ok": true}')
        parts = hub_call.call_args.args[0]
        self.assertEqual(parts[0], "describe")


if __name__ == "__main__":
    unittest.main()
