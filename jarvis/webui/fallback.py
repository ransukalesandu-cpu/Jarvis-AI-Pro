"""When the web UI cannot draw the 3D hologram (no WebGL2), it steps aside for the classic HUD.

Kept apart from host.py (which needs QtWebEngine) so the rule is testable anywhere.
"""
from __future__ import annotations


def on_capability(host, webgl2: bool) -> bool:
    """Hide the web overlay once when WebGL2 is missing. Returns True if it fell back now."""
    if webgl2 or getattr(host, "fell_back", False):
        return False
    host.fell_back = True
    print("[JARVIS] WebGL2 is not available in the web UI; using the classic HUD.")
    host.hide()
    return True
