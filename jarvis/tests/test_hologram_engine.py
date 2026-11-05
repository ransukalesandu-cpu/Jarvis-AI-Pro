"""Runs the real engine (QtWebEngine + software WebGL2) in a child process.

Child process on purpose: a renderer/GPU crash must never take the test session down, and
QtWebEngine has to be imported before the QApplication exists. Skips when WebEngine or WebGL2
is unavailable. This checks logic, bridge, lifecycle and resource release with a *software*
renderer; it says nothing about real GPU speed or Windows behaviour.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

CHILD = textwrap.dedent(r'''
    import json, sys, time
    from jarvis.hologram import prepare_qt
    prepare_qt()
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QTimer, QUrl
        from jarvis.hologram.host import HologramHost, is_allowed_url
    except Exception as exc:
        print("RESULT " + json.dumps({"skip": "no webengine: %r" % (exc,)})); sys.exit(0)

    app = QApplication(sys.argv)
    host = HologramHost(debug=True, quality="low")
    host.resize(640, 720)
    host.show()
    out = {"events": []}
    host.ready.connect(lambda r: out.update(ready=r))
    host.failed.connect(lambda r: out.update(failed=r))
    host._page.report.connect(lambda r: out["events"].append(r["t"]))

    def js(code, key, delay):
        def run():
            host._page.runJavaScript(code, lambda v: out.__setitem__(key, v))
        QTimer.singleShot(delay, run)

    def step_a():
        host.set_state("LISTENING"); host.set_profile("bihansa")
        host.set_reduced_motion(True); host.set_reduced_motion(False)
    def step_b():
        for i in range(20):
            host.set_output_level(0.3 + 0.03 * i, 0.5, 0.1)
    QTimer.singleShot(300, lambda: None)
    # wait for ready, then drive
    def wait_ready():
        if out.get("ready") or out.get("failed"):
            go()
        else:
            QTimer.singleShot(200, wait_ready)
    def go():
        if out.get("failed"): finish(); return
        step_a()
        js("JSON.stringify(window.__holoDebug.state())", "state_listening", 1200)
        QTimer.singleShot(1500, step_b)
        js("JSON.stringify(window.__holoDebug.state())", "state_speaking", 2100)
        js("window.__holo.receive('{\"t\":\"bogus\"}')", "bogus_accepted", 2300)
        js("window.__holo.receive('{\"t\":\"input\",\"v\":9}')", "range_accepted", 2300)
        js("JSON.stringify(window.__holoDebug.counts())", "counts_low", 2400)
        js("window.__holoDebug.setTier('high')", "tier_high", 2500)
        js("JSON.stringify(window.__holoDebug.counts())", "counts_high", 4200)
        js("window.__holoDebug.setTier('low')", "tier_low2", 4400)
        js("JSON.stringify(window.__holoDebug.counts())", "counts_low2", 5600)
        js("window.__holoDebug.frames()", "frames_a", 5700)
        js("window.__holoDebug.loseContext()", "lost", 5800)
        js("window.__holoDebug.restoreContext()", "restored", 6600)
        js("window.__holoDebug.frames()", "frames_b", 6700)
        js("window.__holoDebug.frames()", "frames_c", 8200)
        js("window.__holoDebug.dispose(); JSON.stringify(window.__holoDebug.counts())", "counts_disposed", 8400)
        QTimer.singleShot(8800, finish)
    def finish():
        out["nav"] = {
            "local_index": is_allowed_url(QUrl.fromLocalFile(str(__import__("jarvis.hologram.host", fromlist=["INDEX"]).INDEX))),
            "http": is_allowed_url(QUrl("https://example.com/")),
            "outside": is_allowed_url(QUrl.fromLocalFile("/etc/passwd")),
            "traversal": is_allowed_url(QUrl.fromLocalFile(str(__import__("jarvis.hologram.host", fromlist=["ROOT"]).ROOT) + "/../host.py")),
        }
        host.shutdown()
        print("RESULT " + json.dumps(out)); sys.stdout.flush()
        app.quit()
    QTimer.singleShot(200, wait_ready)
    QTimer.singleShot(60000, lambda: (print("RESULT " + json.dumps({"timeout": True})), app.quit()))
    app.exec()
''')


def _run_child():
    env = dict(os.environ, PYTHONPATH=str(REPO), QT_QPA_PLATFORM="offscreen")
    env.pop("JARVIS_HOLOGRAM", None)
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # containers/CI: Chromium needs these as root, without a GPU
        env["QTWEBENGINE_CHROMIUM_FLAGS"] = ("--no-sandbox --use-gl=angle --use-angle=swiftshader "
                                             "--enable-unsafe-swiftshader --ignore-gpu-blocklist")
    proc = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=150, env=env, cwd=REPO)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        pytest.skip("engine child produced no result (no usable WebEngine here): " + proc.stderr[-300:])
    return json.loads(line[7:])


@pytest.fixture(scope="module")
def result():
    res = _run_child()
    if "skip" in res:
        pytest.skip(res["skip"])
    if res.get("failed"):
        pytest.skip("WebGL2 engine could not start in this environment: " + res["failed"])
    assert not res.get("timeout"), "engine never became ready"
    return res


def test_engine_starts_with_webgl2_and_reports_ready(result):
    assert result["ready"]["webgl2"] is True
    assert result["ready"]["tier"] == "low", "a software renderer must start on the lowest tier"
    assert "ready" in result["events"]


def test_state_and_profile_reach_the_page(result):
    st = json.loads(result["state_listening"])
    assert st["state"] == "listening" and st["profile"] == "bihansa"


def test_output_audio_drives_speaking_independently_of_input(result):
    st = json.loads(result["state_speaking"])
    assert st["state"] == "speaking"


def test_page_rejects_invalid_messages(result):
    assert result["bogus_accepted"] is False
    assert result["range_accepted"] is False


def test_quality_tiers_rebuild_and_release_geometry(result):
    low, high, low2 = (json.loads(result[k]) for k in ("counts_low", "counts_high", "counts_low2"))
    assert high["geometries"] >= low["geometries"]
    assert low2["geometries"] == low["geometries"], "switching tiers must not leak geometry"


def test_webgl_context_loss_and_restore_recover_rendering(result):
    assert result["lost"] is True and result["restored"] is True
    assert "contextlost" in result["events"] and "contextrestored" in result["events"]
    assert result["frames_c"] > result["frames_b"], "frames must keep advancing after the context is restored"


def test_dispose_releases_every_gpu_resource(result):
    gone = json.loads(result["counts_disposed"])
    assert gone["geometries"] == 0 and gone["textures"] == 0


def test_navigation_is_locked_to_the_local_hologram_directory(result):
    nav = result["nav"]
    assert nav["local_index"] is True
    assert nav["http"] is False and nav["outside"] is False and nav["traversal"] is False
