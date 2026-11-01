"""Application runtime boundaries for JARVIS.

The runtime package owns process startup and shutdown orchestration. Feature
implementations remain in their existing modules and are injected at the
application boundary to keep imports light and make lifecycle tests headless.
"""

from core.runtime.application import run_desktop, run_headless

__all__ = ["run_desktop", "run_headless"]
