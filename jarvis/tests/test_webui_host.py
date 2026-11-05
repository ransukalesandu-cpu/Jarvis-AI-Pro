"""WebUI host: navigation lock, bridge round trip, telemetry honesty, bundle integrity."""
from __future__ import annotations

import re

import pytest

from jarvis import webui
from jarvis.webui.telemetry import Telemetry

QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("PyQt6.QtWebEngineCore")
pytest.importorskip("PyQt6.QtWebChannel")


def test_bundle_is_present_and_self_consistent():
    html = (webui.DIST / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', html)
    assert refs, "index.html should reference built assets with relative URLs"
    for r in refs:
        assert (webui.DIST / r).is_file(), r
    assert "https://" not in html and "http://" not in html     # nothing remote
    assert "default-src 'none'" in html                         # strict CSP


def test_navigation_is_locked_to_the_bundle():
    from jarvis.webui.navigation import is_allowed_url
    U = QtCore.QUrl
    assert is_allowed_url(U.fromLocalFile(str(webui.DIST / "index.html")))
    assert not is_allowed_url(U("https://example.com"))
    assert not is_allowed_url(U("javascript:alert(1)"))
    assert not is_allowed_url(U.fromLocalFile("/etc/passwd"))
    assert not is_allowed_url(U.fromLocalFile(str(webui.DIST) + "-evil/index.html"))


def test_bridge_publishes_only_valid_events_and_validates_requests():
    from jarvis.webui.bridge import WebUIBridge
    b = WebUIBridge()
    got, ready, pings = [], [], []
    b.event.connect(got.append)
    b.ready.connect(lambda: ready.append(1))
    b.ping_received.connect(pings.append)
    assert b.publish("assistant.state_changed", state="listening")
    assert not b.publish("assistant.state_changed", state="bogus")
    assert len(got) == 1
    b.request('{"kind":"ready"}')
    b.request('{"kind":"ping","n":7}')
    b.request('{"kind":"delete_everything"}')
    b.request("garbage")
    assert ready == [1] and pings == [7]


def test_telemetry_values_are_real_and_bounded():
    t = Telemetry()
    t.snapshot()
    s = t.snapshot()
    assert s is not None
    assert 0 <= s["cpu"] <= 100 and 0 <= s["ram"] <= 100
    assert s["battery"] is None or 0 <= s["battery"]["percent"] <= 100


def test_ui_mode_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("JARVIS_UI", raising=False)
    assert webui.ui_mode() == "legacy"
    monkeypatch.setenv("JARVIS_UI", "web")
    assert webui.ui_mode() == ("web" if webui.dist_ready() else "legacy")
