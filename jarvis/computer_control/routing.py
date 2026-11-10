"""Steer the model to the Computer Control Engine while it is on (audit P0-3, B3).

With the engine on, the model sees overlapping tools for the same job — e.g. the
older pyautogui ``computer_control`` next to ``cc_control``/``cc_pointer``, and
``ui_automate`` next to ``cc_task`` — and the older descriptions are worded more
strongly. ``flags.tool_routing()`` chooses how that is resolved:

* ``both`` — every tool is offered as before, no guidance (the pre-P0-3 behaviour).
* ``prefer_engine`` (default) — nothing is hidden; :func:`prompt_block` adds a
  short routing section to the system prompt.
* ``engine_only`` — as ``prefer_engine``, and :func:`hidden_tools` also removes
  the older tools listed in :data:`SUPERSEDED`, each only when the readiness check
  its replacement needs passes on this computer. On Linux, or without pywinauto or
  an installed Edge/Chrome, nothing is hidden.

What ``engine_only`` gives up (why it is not the default until measured with
``python -m jarvis.eval.tool_choice --live``): the older ``computer_control``
tool's screenshot-to-file, ``random_data``/``user_data`` form filling and
clipboard copy/paste actions (``cc_control`` hotkeys cover copy/paste), and
``browser_control``'s separate JARVIS Chromium window (``cc_browser`` uses the
installed Edge/Chrome with JARVIS's own profile).

File tools (``files``, ``file_controller``), ``open_app`` (also opens websites and
URIs), ``screen_process`` (live vision into the conversation) and
``autonomous_task`` (engineering work: commands, tests) are never hidden.
"""
from __future__ import annotations

from typing import Iterable

from jarvis.computer_control import flags, readiness

#: older tool -> readiness part its replacement needs
SUPERSEDED: dict[str, str] = {
    "computer_control": "windows",   # -> cc_control / cc_pointer / cc_window
    "ui_interaction": "windows",     # -> cc_control (by accessible name) / cc_screen
    "ui_automate": "windows",        # -> cc_task (planned, verified, cancellable)
    "browser_control": "browser",    # -> cc_browser
}

_CHECKS = {"windows": readiness.windows_check, "browser": readiness.browser_check}


def _ready(parts: Iterable[str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for part in set(parts):
        try:
            out[part] = bool(_CHECKS[part]().ok)
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress(f"computer_control.routing:{part}")
            out[part] = False
    return out


def active_mode() -> str:
    """The routing mode in effect: "off" while the engine is off, else flags.tool_routing()."""
    return flags.tool_routing() if flags.enabled() else "off"


def hidden_tools(ready: dict[str, bool] | None = None) -> frozenset[str]:
    """Names to leave out of the Live tool list (empty unless engine_only and ready)."""
    if active_mode() != "engine_only":
        return frozenset()
    ready = ready if ready is not None else _ready(SUPERSEDED.values())
    return frozenset(name for name, part in SUPERSEDED.items() if ready.get(part))


def prompt_block(offered: Iterable[str], ready: dict[str, bool] | None = None) -> str:
    """System-prompt section for prefer_engine / engine_only; "" otherwise.

    ``offered`` is the final tool list, so the text never names a tool the model
    does not have.
    """
    mode = active_mode()
    names = set(offered)
    if mode not in ("prefer_engine", "engine_only") or "cc_task" not in names:
        return ""
    ready = ready if ready is not None else _ready(("windows", "browser"))
    lines = ["[COMPUTER CONTROL ROUTING]",
             "The Computer Control Engine is on. Its cc_* tools check every action against the "
             "owner's safety policy, ask before risky steps, verify the result and report what "
             "really happened, so prefer them for operating this computer:"]
    if ready.get("windows"):
        lines.append("- Windows apps and windows: cc_app (launch/close), cc_window, and cc_control "
                     "(buttons, menus, text fields by accessible name). Use cc_pointer only when no "
                     "control can be found.")
        lines.append("- A multi-step job across apps or windows (\"open Notepad, write a note and "
                     "save it\"): call cc_task with the whole objective. This is the exception to "
                     "preferring direct tools: cc_task plans, verifies and can be cancelled.")
    else:
        lines.append("- Windows app control (cc_app, cc_window, cc_control, cc_pointer, cc_task) is "
                     "not available on this computer; use the other tools for apps. Call "
                     "cc_engine_status if the owner asks why.")
    if ready.get("browser") and "cc_browser" in names:
        lines.append("- Operating a web page (search, click, fill a form, read it): cc_browser. "
                     "open_app still just opens a website.")
    lines.append("- Finding a target on screen, clicking it safely or checking that text is "
                 "visible: cc_screen. To simply look at the screen and describe it, keep using "
                 "screen_process.")
    if "cc_file" in names:
        lines.append("- File changes made as part of computer-control work: cc_file (deletes go to "
                     "the Recycle Bin, nothing is overwritten silently, every change is verified).")
    if "autonomous_task" in names:
        lines.append("- autonomous_task stays the tool for engineering work (commands, code, tests).")
    lines.append("- Saying 'Jarvis, stop' or calling cc_emergency_stop halts computer control at once.")
    return "\n".join(lines)
