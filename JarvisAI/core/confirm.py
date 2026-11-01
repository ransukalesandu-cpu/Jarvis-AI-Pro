"""
core/confirm.py — voice-only confirmation for consequential actions.

    The model cannot create or resolve a confirmation token. The application
    stores the callable locally and accepts only an explicit spoken phrase
    while that exact request is pending. No confirmation HUD or popup is shown.
    Ordinary low-risk actions never reach this module; they execute directly
    through the risk policy in core/security.py.

WHAT BELONGS HERE AND WHAT DOES NOT
    Only genuinely irreversible things. Anything that can be reversed should be
    done at once and pushed onto core/undo.py instead — undo is faster than a
    question, and an assistant that asks before every action is one nobody uses.
"""

from __future__ import annotations

import threading
import time
import re
from dataclasses import dataclass
from typing import Callable, Optional

from core import failsoft

# A pending confirmation is abandoned after this long. Chosen to outlast a
# normal "hang on, let me look at the screen" pause without leaving a live
# shutdown button sitting on the HUD for the rest of the day.
TIMEOUT_SECONDS = 90.0


@dataclass
class _Pending:
    key:     str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float


_pending: Optional[_Pending] = None
_lock = threading.Lock()
# All confirmation-gated operations use the voice-only path. The pending
# request is local, time-limited, and can only be resolved by an explicit phrase.

# Set once at startup by main.py. Signature: (title, detail) -> None for show,
# and () -> None for hide. Both are marshalled onto the Qt thread by the UI.
_show_cb: Optional[Callable[[str, str], None]] = None
_hide_cb: Optional[Callable[[], None]] = None
_log_cb:  Optional[Callable[[str], None]] = None


def bind(show, hide, log=None) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _hide_cb, _log_cb
    _show_cb, _hide_cb, _log_cb = show, hide, log


def is_bound() -> bool:
    """True when the confirmation service is wired into the running assistant.

    Voice confirmation does not require a visible UI. The callback binding is
    retained for compatibility with the existing startup wiring.
    """
    return _log_cb is not None


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            failsoft.suppress('core.confirm:_log')


def request(key: str, title: str, detail: str, run: Callable[[], str]) -> str:
    """Park a consequential action until the user explicitly confirms by voice.

    No UI callback is invoked: the returned instruction is spoken by JARVIS.
    """
    global _pending

    with _lock:
        if _pending is not None and time.monotonic() - _pending.at <= TIMEOUT_SECONDS:
            existing_title = _pending.title
            _log(f"SYS: Refused to replace pending confirmation — {existing_title}")
            return (
                f"A different confirmation is already waiting: {existing_title}. "
                "Resolve or cancel it before requesting another action."
            )
        if _pending is not None:
            _pending = None
        _pending = _Pending(key=key, title=title, detail=detail,
                            run=run, at=time.monotonic())

    _log(f"SYS: Awaiting spoken confirmation — {title}")
    spoken_detail = f" Details: {detail}." if detail else ""
    return (
        f"[CONFIRMATION_PENDING] Ask the user aloud: "
        f"'{title}.{spoken_detail} Say confirm action to proceed, or cancel action to cancel.' "
        "Do not show a popup, do not execute yet, and do not claim it is done."
    )


def resolve(accepted: bool, source: str = "HUD") -> None:
    """Called by the UI when the user presses CONFIRM or CANCEL.

    Runs the stored callable on a worker thread — this is invoked from the Qt
    thread, and shutting the machine down from inside a button handler would
    freeze the interface on its way out."""
    global _pending

    with _lock:
        p, _pending = _pending, None

    _finish(p, accepted, source)


def _finish(p: _Pending | None, accepted: bool, source: str) -> None:
    """Complete an already-claimed confirmation without holding `_lock`."""

    if source != "voice" and _hide_cb:
        try:
            _hide_cb()
        except Exception:
            failsoft.suppress('core.confirm:_finish')

    if p is None:
        return

    if time.monotonic() - p.at > TIMEOUT_SECONDS:
        _log(f"SYS: Confirmation expired — {p.title}")
        return

    if not accepted:
        _log(f"SYS: Cancelled via {source} — {p.title}")
        return

    def _worker():
        try:
            result = p.run() or "Done."
            _log(f"SYS: Request granted via {source} — {p.title}. {result}")
        except Exception as e:
            _log(f"ERR: {p.title} failed — {e}")

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def resolve_by_voice(text: str) -> str | None:
    """Resolve a pending action only for an exact phrase and verified speaker.

    Requiring an explicit phrase, and only accepting it while a live confirmation
    is pending, avoids treating ordinary speech such as "yes" as approval.
    Speaker-model inference runs outside `_lock`, so a slow check never blocks a
    manual HUD click; the pending object is checked again before consuming it.
    """
    phrase = " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold()))
    # Only these complete phrases resolve a pending request. Bare yes/no,
    # generic confirm, and casual approval words are deliberately ignored.
    accepted = {"confirm action"}
    rejected = {"cancel action"}
    if phrase in accepted:
        decision, label = True, "approved"
    elif phrase in rejected:
        decision, label = False, "cancelled"
    else:
        return None

    global _pending
    with _lock:
        pending = _pending
        if pending is None or time.monotonic() - pending.at > TIMEOUT_SECONDS:
            if pending is not None:
                _pending = None
            return None
    if decision:
        try:
            from core import security
            # During the explicitly configured development phase owner Voice ID
            # is disabled. When it is enabled again, require verified live owner
            # speech before accepting the spoken approval.
            if security.voice_id_required() and not security.authorize_voice_confirmation():
                _log(f"SEC: Voice ID blocked spoken approval for {pending.title}.")
                return "voice_id_required"
        except Exception:
            _log(f"SEC: Voice authorization unavailable; spoken approval denied for {pending.title}.")
            return "voice_id_required"
    with _lock:
        if _pending is not pending:
            return "confirmation_changed"
        _pending = None
    _finish(pending, decision, source="voice")
    return label


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    global _pending
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            _pending = None
            return ""
        return _pending.title
