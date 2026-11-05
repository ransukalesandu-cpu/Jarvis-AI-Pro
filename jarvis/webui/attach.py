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
    from .command_gate import CommandGate

    sink = getattr(window, "_submit_immersive_command", None)   # logs "You: …" and hands off to the assistant
    gate = CommandGate(sink, security.get_auth_manager, lambda: identity.get_identity_manager().guest_mode_active())
    cw = window.centralWidget()
    host = WebUIHost(cw, gate=gate)
    host.setGeometry(cw.rect())
    cw.installEventFilter(_Fit(cw, host))
    host.show()
    host.raise_()
    host._live = LiveLink(host)
    window._web_ui = host
    return host
