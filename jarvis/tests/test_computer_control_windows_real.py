"""Project 1 on a real Windows desktop (runs in the windows-latest CI job).

Only touches what it starts itself: one Notepad on a temporary file. Anything it
launched is killed in teardown even when an assertion fails. Skipped off Windows.
"""
from __future__ import annotations

import os
import time

import pytest

pytestmark = [pytest.mark.windows_only,
              pytest.mark.skipif(os.name != "nt", reason="needs a real Windows desktop")]


@pytest.fixture
def real(tmp_path):
    from jarvis.computer_control import estop
    from jarvis.computer_control.runner import ActionContext
    from jarvis.computer_control.windows.controller import WindowsController
    from jarvis.computer_control.windows.fallback_input import FallbackInput
    from jarvis.computer_control.windows.uia import PywinautoBackend

    backend = PywinautoBackend()
    ok, reason = backend.available()
    assert ok, reason
    controller = WindowsController(backend, FallbackInput(min_interval_s=0.0), launch_timeout=25.0, poll=0.25)
    started: list[int] = []

    def ctx(params=None):
        return ActionContext("real-test", dict(params or {}), estop.token())

    yield backend, controller, ctx, started, tmp_path
    for pid in started:
        try:
            backend.terminate(pid, force=True)
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("tests.windows_real:teardown")


def _editor(controller, ctx, window_query):
    from jarvis.computer_control.windows.model import ElementQuery
    for control_type in ("Edit", "Document"):
        out = controller.find(ctx(), window_query, ElementQuery(control_type=control_type))
        if out.ok and out.data["elements"]:
            return ElementQuery(ref=out.data["elements"][0]["ref"])
    raise AssertionError("Notepad exposes no Edit/Document control")


def test_discovers_apps_and_windows(real):
    backend, controller, ctx, _started, _tmp = real
    installed = controller.list_installed(ctx())
    assert installed.ok and installed.data["total"] > 0, installed.message
    running = controller.list_running(ctx())
    assert running.ok
    assert backend.screen_size()[0] > 0


def test_notepad_end_to_end(real):
    from jarvis.computer_control.windows.model import WindowQuery

    backend, controller, ctx, started, tmp = real
    note = tmp / "jarvis_cc_note.txt"
    note.write_text("start", encoding="utf-8")

    launched = controller.launch(ctx(), "notepad.exe", [str(note)])
    assert launched.ok, launched.message
    if launched.data.get("pid"):
        started.append(int(launched.data["pid"]))
    assert launched.verified, launched.message
    window = launched.data["window"]
    started.append(int(window["pid"]))
    query = WindowQuery(handle=int(window["handle"]))

    activated = controller.activate(ctx(), query)
    assert activated.ok, activated.message

    editor = _editor(controller, ctx, query)
    typed = controller.set_text(ctx(), query, editor, "Hello JARVIS")
    assert typed.ok, typed.message
    assert typed.verified, typed.evidence

    # Save through the UIA menu (no simulated input: CI runners have no interactive
    # input desktop, so SendInput-based hotkeys are pending owner validation).
    saved = controller.menu(ctx(), query, "File->Save")
    assert saved.ok, saved.message
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and note.read_text(encoding="utf-8", errors="replace").strip() != "Hello JARVIS":
        time.sleep(0.25)
    assert note.read_text(encoding="utf-8", errors="replace").strip() == "Hello JARVIS"

    moved = controller.move_resize(ctx(), query, 50, 60, 700, 500)
    assert moved.ok, moved.message
    assert moved.verified, moved.evidence
    assert controller.set_state(ctx(), query, "minimize").ok
    assert controller.set_state(ctx(), query, "restore").ok

    inspected = controller.inspect_window(ctx(), query)
    assert inspected.ok and inspected.data["elements"], inspected.message

    closed = controller.close_window(ctx(), query)
    assert closed.ok and closed.verified, closed.message


def test_missing_control_is_reported_not_guessed(real):
    from jarvis.computer_control.windows.model import ElementQuery, WindowQuery

    backend, controller, ctx, started, tmp = real
    launched = controller.launch(ctx(), "notepad.exe", [])
    assert launched.ok and launched.verified, launched.message
    started.append(int(launched.data["window"]["pid"]))
    query = WindowQuery(handle=int(launched.data["window"]["handle"]))
    out = controller.invoke(ctx(), query, ElementQuery(name="Definitely Not A Button 123"))
    assert not out.ok and "No control" in out.message
