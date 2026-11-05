"""The native (PyQt6) approval prompt for HIGH-risk computer-control actions.

Shown by the Python process itself — never by the web UI — so page content or
JavaScript cannot draw, answer or skip it. The dialog says what will happen and
why it needs approval; when an owner PIN is enrolled it asks for the PIN in a
password field (the PIN is handed to AuthManager.verify_pin by
:class:`approval.NativeApprover`, never logged).

Qt is imported lazily so the package stays importable on headless runners.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from jarvis.computer_control.approval import ApprovalRequest, PromptAnswer


def _pin_enrolled() -> bool:
    try:
        from jarvis.core import security
        return bool(security.get_auth_manager().is_pin_enrolled())
    except Exception:
        return False


def _show(parent: Any, request: ApprovalRequest) -> Optional[PromptAnswer]:
    from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

    details = "\n".join(f"  {k}: {v}" for k, v in list(request.details.items())[:8])
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("JARVIS — approve high-risk action")
    box.setText(f"{request.summary}\n\nAction: {request.action}  (risk: {request.level.value})")
    box.setInformativeText(f"Why approval is needed: {request.reason}")
    if details:
        box.setDetailedText(details)
    approve = box.addButton("Approve", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Deny", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(QMessageBox.StandardButton.NoButton)
    box.exec()
    if box.clickedButton() is not approve:
        return PromptAnswer(False, method="native_prompt")
    if not _pin_enrolled():
        return PromptAnswer(True, method="native_prompt")
    pin, ok = QInputDialog.getText(parent, "JARVIS Owner Verification",
                                   "Enter the owner PIN to approve this action:",
                                   QLineEdit.EchoMode.Password)
    if not ok or not pin:
        return PromptAnswer(False, method="native_prompt")
    return PromptAnswer(True, pin=str(pin), method="native_prompt+pin")


def make_prompt(parent_getter: Callable[[], Any],
                post_to_ui_thread: Callable[[Callable[[], None]], None]):
    """Build the ``prompt(request, timeout)`` function for approval.bind_native_prompt.

    ``post_to_ui_thread(fn)`` must run ``fn`` on the Qt thread (the UI passes a
    queued signal emit). The caller's worker thread waits up to ``timeout``.
    """

    def prompt(request: ApprovalRequest, timeout: float) -> Optional[PromptAnswer]:
        from PyQt6.QtCore import QThread
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return None
        result: list[Optional[PromptAnswer]] = [None]
        done = threading.Event()

        def run() -> None:
            if done.is_set():          # the worker already gave up
                return
            try:
                result[0] = _show(parent_getter(), request)
            finally:
                done.set()

        if QThread.currentThread() == app.thread():
            run()
        else:
            post_to_ui_thread(run)
            if not done.wait(timeout=max(1.0, float(timeout))):
                done.set()
                return None
        return result[0]

    return prompt
