"""Owner approval for HIGH-risk computer-control actions.

Rules (owner decision 9 / SECURITY_MODEL.md):

* Approval comes from a **native** prompt only — a Qt dialog owned by the
  Python process, checked against AuthManager (Privacy Lock, owner session,
  PIN). The web page / JavaScript bridge has no way to call or answer it: the
  prompt function is bound from Python (:func:`bind_native_prompt`) and nothing
  in ``jarvis/webui`` references this module.
* No approver bound → **deny** (fail closed). A headless run can never approve.
* Privacy Lock → deny without showing anything.
* When an owner PIN is enrolled, a HIGH action needs the PIN typed into the
  native prompt and verified by ``AuthManager.verify_pin`` (wrong PINs count
  towards the existing lockout). Without an enrolled PIN the owner session must
  already be verified and the owner must click Approve.
* A prompt that is not answered within ``timeout`` seconds is a deny.
* Approval never carries over: each HIGH action is asked separately.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from jarvis.computer_control.policy import Level

DEFAULT_TIMEOUT_S = 90.0


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    level: Level
    summary: str                     # one human sentence: what will happen
    reason: str                      # why it needs approval
    details: dict = field(default_factory=dict)   # already redacted
    task_id: str = ""


@dataclass(frozen=True)
class PromptAnswer:
    approved: bool
    pin: Optional[str] = None
    method: str = "native_prompt"


@dataclass(frozen=True)
class ApprovalResult:
    approved: bool
    method: str
    reason: str


class Approver(Protocol):  # pragma: no cover - structural
    def request(self, req: ApprovalRequest, timeout: float = DEFAULT_TIMEOUT_S) -> ApprovalResult: ...


class DenyAllApprover:
    """The default: nobody is present to approve, so nothing HIGH runs."""

    def request(self, req: ApprovalRequest, timeout: float = DEFAULT_TIMEOUT_S) -> ApprovalResult:
        return ApprovalResult(False, "none", "No native approval prompt is available, so the "
                                             "high-risk action was not performed.")


PromptFn = Callable[[ApprovalRequest, float], Optional[PromptAnswer]]


class NativeApprover:
    """AuthManager-checked approval through an injected native prompt."""

    def __init__(self, prompt: PromptFn, *, auth_manager: Any = None) -> None:
        self._prompt = prompt
        self._auth_manager = auth_manager
        self._lock = threading.Lock()      # one prompt at a time

    def _manager(self):
        if self._auth_manager is not None:
            return self._auth_manager
        from jarvis.core import security
        return security.get_auth_manager()

    def request(self, req: ApprovalRequest, timeout: float = DEFAULT_TIMEOUT_S) -> ApprovalResult:
        try:
            manager = self._manager()
        except Exception:
            return ApprovalResult(False, "none", "Owner authentication is unavailable.")
        try:
            if manager.is_privacy_lock_active():
                return ApprovalResult(False, "privacy_lock", "Privacy Lock is active.")
            pin_enrolled = bool(manager.is_pin_enrolled())
            owner_ok = bool(manager.is_owner_access_allowed())
        except Exception:
            return ApprovalResult(False, "none", "Owner authentication state could not be read.")
        if not pin_enrolled and not owner_ok:
            return ApprovalResult(False, "none", "Owner verification is required first.")

        if not self._lock.acquire(timeout=1.0):
            return ApprovalResult(False, "busy", "Another approval is already waiting.")
        try:
            try:
                answer = self._prompt(req, float(timeout))
            except Exception as exc:
                return ApprovalResult(False, "error", f"The approval prompt failed: {type(exc).__name__}.")
        finally:
            self._lock.release()

        if answer is None:
            return ApprovalResult(False, "timeout", "The approval prompt was not answered.")
        try:
            # the lock may have come on while the prompt was open
            if manager.is_privacy_lock_active():
                return ApprovalResult(False, "privacy_lock",
                                      "Privacy Lock became active while the prompt was open.")
        except Exception:
            return ApprovalResult(False, "none", "Owner authentication state could not be read.")
        if not answer.approved:
            return ApprovalResult(False, answer.method, "The owner declined.")
        if pin_enrolled:
            pin = str(answer.pin or "")
            if not pin:
                return ApprovalResult(False, answer.method, "The owner PIN is required.")
            try:
                if not manager.verify_pin(pin):
                    return ApprovalResult(False, "pin", "The PIN was not accepted.")
            except Exception:
                return ApprovalResult(False, "pin", "The PIN could not be verified.")
            return ApprovalResult(True, "pin", "Approved with the owner PIN.")
        return ApprovalResult(True, answer.method, "Approved by the verified owner.")


_lock = threading.Lock()
_approver: Approver = DenyAllApprover()


def get_approver() -> Approver:
    with _lock:
        return _approver


def set_approver(approver: Optional[Approver]) -> None:
    global _approver
    with _lock:
        _approver = approver if approver is not None else DenyAllApprover()


def bind_native_prompt(prompt: PromptFn, *, auth_manager: Any = None) -> NativeApprover:
    """Called once by the desktop UI (Python side) with its Qt prompt function."""
    approver = NativeApprover(prompt, auth_manager=auth_manager)
    set_approver(approver)
    return approver
