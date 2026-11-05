"""Mounts the web UI over the legacy window's central area when ``JARVIS_UI=web``.

The legacy HUD stays underneath (the fallback), untouched. Unset or invalid => this does nothing.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject


class _Fit(QObject):
    """Keeps the overlay exactly as large as the central widget."""

    def __init__(self, target, overlay):
        super().__init__(overlay)
        self._target, self._overlay = target, overlay

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt API)
        if obj is self._target and ev.type() == QEvent.Type.Resize:
            self._overlay.setGeometry(self._target.rect())
        return False


def attach(window):
    from . import ui_mode

    if ui_mode() != "web":
        return None
    from .host import WebUIHost
    from .live import LiveLink

    from jarvis.core import identity, security
    from .command_gate import CommandGate, ControlGate

    sink = getattr(window, "_submit_immersive_command", None)   # logs "You: …" and hands off to the assistant
    gate = CommandGate(sink, security.get_auth_manager, lambda: identity.get_identity_manager().guest_mode_active())
    cw = window.centralWidget()
    actions = {}
    for name, attr in ("interrupt", "_do_interrupt"), ("mute", "_toggle_mute"), ("unmute", "_toggle_mute"), ("fullscreen", "_toggle_fullscreen"):
        if callable(getattr(window, attr, None)):
            actions[name] = getattr(window, attr)
    already = {}
    mode_btn = getattr(window, "_mode_btn", None)
    if mode_btn is not None:
        for i, persona in enumerate(("jarvis", "bihansa")):
            actions[f"mode_{persona}"] = lambda i=i: mode_btn.setCurrentIndex(i)
            already[f"mode_{persona}"] = lambda i=i: mode_btn.currentIndex() == i
    if callable(getattr(window, "set_performance_budget", None)):
        for choice in ("auto", "full", "balanced", "lite"):
            actions[f"perf_{choice}"] = lambda c=choice: window.set_performance_budget(c, save=True)
        from jarvis.core import ui_state
        for choice in ("full", "balanced", "lite"):     # "auto" has no fixed tier to compare with, so it always applies
            already[f"perf_{choice}"] = lambda c=choice: (getattr(window, "_perf_gov", None) is not None
                                                          and bool(getattr(window._perf_gov, "pinned", False))
                                                          and ui_state.bus().get(ui_state.PERF_TIER) == c)
    controls = ControlGate(gate, actions, lambda: bool(getattr(window, "_muted", False)), already=already)
    host = WebUIHost(cw, gate=gate, controls=controls)
    host.setGeometry(cw.rect())
    cw.installEventFilter(_Fit(cw, host))
    host.show()
    host.raise_()
    host._live = LiveLink(host)
    from .log_feed import LogFeed

    host._log_feed = LogFeed(gate.availability, parent=host)
    host._log_feed.line.connect(host.push_log)
    window._web_ui = host
    return host
