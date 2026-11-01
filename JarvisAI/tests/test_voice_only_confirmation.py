from __future__ import annotations

import threading

from core import confirm
from core import security


def setup_function():
    # Ensure tests never inherit a pending request from another test.
    confirm.resolve(False, source="test-reset")


def test_dangerous_confirmation_is_spoken_without_showing_popup(monkeypatch):
    shown = []
    completed = threading.Event()
    confirm.bind(
        show=lambda title, detail: shown.append((title, detail)),
        hide=lambda: None,
        log=lambda message: None,
    )
    monkeypatch.setattr(security, "voice_id_required", lambda: False)
    monkeypatch.setattr(
        security,
        "authorize_voice_confirmation",
        lambda: (_ for _ in ()).throw(AssertionError("Voice ID is disabled")),
    )

    response = confirm.request(
        "sec-file-delete",
        "Delete file",
        "File: report.txt",
        lambda: (completed.set() or "deleted"),
    )

    assert "[VOICE_CONFIRMATION_PENDING]" in response
    assert "confirm action" in response
    assert "report.txt" in response
    assert shown == []
    assert confirm.pending_title() == "Delete file"

    # A casual affirmative must not approve the pending dangerous action.
    assert confirm.resolve_by_voice("yes") is None
    assert not completed.is_set()

    assert confirm.resolve_by_voice("confirm action") == "approved"
    assert completed.wait(2)
    assert shown == []


def test_cancel_action_cancels_without_running_callback():
    ran = []
    confirm.bind(show=lambda *_: None, hide=lambda: None, log=lambda _: None)

    confirm.request(
        "sec-shutdown",
        "Shut down computer",
        "Power off the computer",
        lambda: ran.append(True) or "shutdown",
    )

    assert confirm.resolve_by_voice("cancel action") == "cancelled"
    assert ran == []
    assert confirm.pending_title() == ""


def test_generic_confirm_is_not_accepted():
    confirm.bind(show=lambda *_: None, hide=lambda: None, log=lambda _: None)
    confirm.request("sec-delete", "Delete data", "Target: data", lambda: "done")

    assert confirm.resolve_by_voice("confirm") is None
    assert confirm.pending_title() == "Delete data"
    confirm.resolve(False, source="test-cleanup")
