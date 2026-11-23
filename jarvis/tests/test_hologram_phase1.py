"""Hologram engine V2, phase 1: perf messages, the web-process sampler, and the warning state."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from jarvis.webui import contract
from jarvis.webui.render_perf import MIN_INTERVAL_S, RenderPerf

PERF = {"fps": 58, "frameMs": 17.2, "drawCalls": 41, "triangles": 23800, "heapMb": 64, "dpr": 1.5}


def req(**m):
    return json.dumps({"kind": "hologram.perf", **m})


def test_perf_request_accepted_and_bounded():
    assert contract.parse_request(req(**PERF)) is not None
    assert contract.parse_request(req(**{**PERF, "heapMb": None})) is not None
    for bad in ({"fps": -1}, {"dpr": 9}, {"drawCalls": 1.5}, {"drawCalls": True}, {"heapMb": "x"}, {"frameMs": float("inf")}):
        assert contract.parse_request(req(**{**PERF, **bad})) is None, bad
    assert contract.parse_request(req(**{**PERF, "extra": 1})) is None
    assert contract.parse_request(json.dumps({"kind": "hologram.perf", "fps": 60})) is None


def test_perf_report_event_bounded():
    assert contract.encode_event("hologram.perf_report", cpu=7.5, ramMb=380.2, processes=2) is not None
    assert contract.encode_event("hologram.perf_report", cpu=101, ramMb=1, processes=1) is None
    assert contract.encode_event("hologram.perf_report", cpu=1, ramMb=1, processes=1.5) is None
    assert contract.encode_event("hologram.perf_report", cpu=1, ramMb=1) is None


def test_warning_state_is_part_of_the_contract():
    assert "warning" in contract.ASSISTANT_STATES
    assert contract.encode_event("assistant.state_changed", state="warning") is not None


def test_sampler_measures_real_qtwebengine_children(tmp_path):
    """Spawn a child process literally named QtWebEngineProcess and check it is found and measured."""
    pytest.importorskip("psutil")
    if sys.platform == "win32":
        pytest.skip("uses a symlinked interpreter name")
    exe = tmp_path / "QtWebEngineProcess"
    os.symlink(sys.executable, exe)
    child = subprocess.Popen([str(exe), "-c", "import time\nx=0\nt=time.time()\nwhile time.time()-t<3: x+=1"])
    try:
        import time
        rp = RenderPerf()
        first = rp.sample()                 # primes the counter
        time.sleep(0.6)
        s = rp.sample()
        assert first is not None and s is not None
        assert s["processes"] >= 1
        assert s["ramMb"] > 1
        assert 0 < s["cpu"] <= 100          # a busy loop: real, non-zero CPU
    finally:
        child.kill()
        child.wait()


def test_on_page_throttles_and_keeps_latest():
    t = [100.0]
    rp = RenderPerf(clock=lambda: t[0])
    rp.sample = lambda: {"cpu": 1.0, "ramMb": 2.0, "processes": 1}  # type: ignore[method-assign]
    assert rp.on_page(PERF) == {"cpu": 1.0, "ramMb": 2.0, "processes": 1}
    assert rp.on_page({**PERF, "fps": 30}) is None          # too soon
    assert rp.page["fps"] == 30                              # but the page numbers are kept
    t[0] += MIN_INTERVAL_S
    assert rp.on_page(PERF) is not None


def test_bridge_emits_perf():
    pytest.importorskip("PyQt6.QtCore")
    from jarvis.webui.bridge import WebUIBridge
    b = WebUIBridge()
    got = []
    b.perf.connect(got.append)
    b.request(req(**PERF))
    b.request(req(**{**PERF, "dpr": 0}))
    assert got == [PERF]
