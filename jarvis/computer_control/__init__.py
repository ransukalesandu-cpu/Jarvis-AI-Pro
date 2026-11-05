"""JARVIS Computer Control Engine.

Every desktop/browser/visual action JARVIS performs on the owner's computer goes
through one pipeline (:mod:`jarvis.computer_control.runner`)::

    feature flag -> emergency stop -> policy -> approval -> audit
                 -> timeout/cancel -> execute -> verify -> audit

The engine is OFF by default (``JARVIS_COMPUTER_CONTROL=1`` turns it on, the
same opt-in style as ``JARVIS_UI=web``) and has a dry-run mode
(``JARVIS_COMPUTER_CONTROL_DRY_RUN=1``) that plans and logs but performs no
action. See docs/computer-control/MASTER_ARCHITECTURE.md.

Nothing in this package imports Qt, pywinauto, pyautogui or Playwright at module
import time, so it loads (and is tested) on a headless Linux runner.
"""
from __future__ import annotations

__all__ = ["flags", "policy", "approval", "estop", "audit", "untrusted", "contract", "runner"]
