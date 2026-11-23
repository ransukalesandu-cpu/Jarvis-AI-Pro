"""scrcpy live screen: args, start/stop, failures, tool wiring."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from jarvis.laptop_agent.devices.scrcpy import ScrcpyError, ScrcpyManager, build_args, find_scrcpy


class FakeProc:
    def __init__(self, exits_with=None, err=b""):
        self.exits_with = exits_with
        self.terminated = False

        class Err:
            def read(self_inner):
                return err
        self.stderr = Err()

    def poll(self):
        return 0 if self.terminated else self.exits_with

    def wait(self, timeout=None):
        if self.exits_with is None and not self.terminated:
            raise subprocess.TimeoutExpired("scrcpy", timeout)
        return self.exits_with or 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


def test_build_args():
    args = build_args("scrcpy", "SER", title="JARVIS - phone")
    assert args[:3] == ["scrcpy", "--serial", "SER"]
    assert "--stay-awake" in args and "--no-audio" in args and "--no-control" not in args
    view = build_args("scrcpy", "SER", title="t", control=False)
    assert "--no-control" in view and "--stay-awake" not in view


def test_show_hide_cycle():
    started = []

    def popen(args, **kw):
        started.append((args, kw["env"].get("ADB")))
        return FakeProc()
    mgr = ScrcpyManager(popen=popen, finder=lambda: "scrcpy")
    assert "Showing the phone" in mgr.show("phone", "100.1.2.3:5555", adb_path="C:/adb.exe")
    assert started[0][1] == "C:/adb.exe"
    assert mgr.is_open("phone")
    assert "already open" in mgr.show("phone", "x")
    assert len(started) == 1
    assert "Closed" in mgr.hide("phone")
    assert not mgr.is_open("phone")
    assert "not open" in mgr.hide("phone")


def test_missing_scrcpy_and_immediate_exit():
    with pytest.raises(ScrcpyError, match="not installed"):
        ScrcpyManager(finder=lambda: None).show("phone", "s")
    mgr = ScrcpyManager(popen=lambda a, **k: FakeProc(exits_with=1, err=b"ERROR: Device disconnected\n"),
                        finder=lambda: "scrcpy")
    with pytest.raises(ScrcpyError, match="Device disconnected"):
        mgr.show("phone", "s")


def test_find_scrcpy_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "scrcpy.exe"
    exe.write_text("")
    monkeypatch.setenv("JARVIS_SCRCPY", str(exe))
    assert find_scrcpy() == str(exe)
    monkeypatch.setenv("JARVIS_SCRCPY", str(tmp_path / "missing.exe"))
    assert find_scrcpy() is None


def test_phone_control_show_screen_uses_manager():
    from jarvis.actions import phone_control as pc

    class Mgr:
        def show(self, name, serial, adb_path="", control=True):
            return f"show {name} {serial} {control}"

        def hide(self, name):
            return f"hide {name}"
    with patch.object(pc, "find_adb", return_value="adb"), \
            patch.object(pc, "_resolve_device", return_value=("SER", "")), \
            patch("jarvis.laptop_agent.devices.scrcpy.get_manager", return_value=Mgr()):
        assert pc.phone_control({"action": "show_screen"}) == "show phone SER True"
        assert pc.phone_control({"action": "show_screen", "control": False}) == "show phone SER False"
        assert pc.phone_control({"action": "hide_screen"}) == "hide phone"


def test_agent_tool_declared():
    from jarvis.laptop_agent import android_tools

    assert "phone_screen" in {d["name"] for d in android_tools.DECLARATIONS}
