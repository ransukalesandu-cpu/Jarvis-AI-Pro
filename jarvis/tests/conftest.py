"""Test-session setup.

HUD tests do not need a real Chromium process, so the hologram is switched off for them
(JARVIS_HOLOGRAM=off -> inert stand-in). The real host is exercised in a separate process by
``test_hologram_engine.py`` so a renderer crash can never take the test session down.
"""
import os

os.environ.setdefault("JARVIS_HOLOGRAM", "off")
