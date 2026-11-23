"""Remote ADB over Tailscale: transport labels, fallback address, tcpip enable."""
from __future__ import annotations

import pytest

from jarvis.laptop_agent.devices.android import (
    Adb, AndroidDevice, AndroidManager, AndroidTarget, transport_of,
)
from jarvis.tests.test_agent_android import FakeAdb

HOME = "192.168.1.50:5555"
REMOTE = "100.101.102.103:5555"


@pytest.mark.parametrize("serial,kind", [
    ("ABC123", "usb"), ("192.168.1.50:5555", "wifi"), ("100.101.102.103:5555", "tailscale"),
    ("my-phone.tail1234.ts.net:5555", "tailscale"), ("100.200.1.1:5555", "wifi"),
])
def test_transport_of(serial, kind):
    assert transport_of(serial) == kind


def test_away_from_home_uses_tailscale_address():
    fake = FakeAdb(devices={}, reachable=[REMOTE])
    try:
        adb = Adb(fake.path)
        target = AndroidTarget("phone", address=HOME, remote_address=REMOTE)
        status = AndroidManager([target], adb).poll()
        assert status["phone"]["online"]
        assert status["phone"]["serial"] == REMOTE
        assert status["phone"]["transport"] == "tailscale"
        connects = [e["args"][1] for e in fake.log() if e["args"][:1] == ["connect"]]
        assert connects == [HOME, REMOTE]          # home first, Tailscale as fallback
    finally:
        fake.stop()


def test_at_home_prefers_home_address():
    fake = FakeAdb(devices={}, reachable=[HOME, REMOTE])
    try:
        target = AndroidTarget("phone", address=HOME, remote_address=REMOTE)
        status = AndroidManager([target], Adb(fake.path)).poll()
        assert status["phone"]["serial"] == HOME
        connects = [e["args"][1] for e in fake.log() if e["args"][:1] == ["connect"]]
        assert connects == [HOME]
    finally:
        fake.stop()


def test_enable_remote_runs_tcpip_and_configure_reads_remote_address():
    fake = FakeAdb(devices={}, reachable=[HOME])
    try:
        adb = Adb(fake.path)
        mgr = AndroidManager([], adb)
        mgr.configure([{"name": "phone", "address": HOME, "remote_address": REMOTE}])
        mgr.poll()
        msg = mgr.get("phone").enable_remote()
        assert REMOTE in msg
        assert any(e["args"] == ["tcpip", "5555"] for e in fake.log())
    finally:
        fake.stop()


def test_remote_access_tool_declared():
    from jarvis.laptop_agent import android_tools

    assert "remote_access" in {d["name"] for d in android_tools.DECLARATIONS}
    assert android_tools.META["remote_access"]["risk"] == "destructive"
    dev = AndroidDevice(AndroidTarget("phone"), Adb("adb"))
    assert dev.target.wireless() == []
