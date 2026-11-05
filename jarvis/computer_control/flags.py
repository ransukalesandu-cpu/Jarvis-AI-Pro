"""Feature flag and dry-run switch for the Computer Control Engine.

* ``JARVIS_COMPUTER_CONTROL`` — ``1``/``true``/``on``/``yes`` enables the engine.
  Anything else (including unset) keeps it OFF: no computer-control tool is
  offered to the model and :class:`~jarvis.computer_control.runner.ActionRunner`
  refuses every action with status ``disabled``.
* ``JARVIS_COMPUTER_CONTROL_DRY_RUN`` — when on, actions are classified,
  approved and logged exactly as for real, but the handler is never called.

Tests (and the settings panel later) can override both without touching the
process environment through :func:`override`.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

ENV_ENABLED = "JARVIS_COMPUTER_CONTROL"
ENV_DRY_RUN = "JARVIS_COMPUTER_CONTROL_DRY_RUN"
_TRUE = frozenset({"1", "true", "on", "yes", "enabled"})

_lock = threading.Lock()
_enabled_override: Optional[bool] = None
_dry_run_override: Optional[bool] = None


def _env_true(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def enabled() -> bool:
    """True only when the owner opted in."""
    with _lock:
        if _enabled_override is not None:
            return _enabled_override
    return _env_true(ENV_ENABLED)


def dry_run() -> bool:
    with _lock:
        if _dry_run_override is not None:
            return _dry_run_override
    return _env_true(ENV_DRY_RUN)


def set_overrides(*, enabled: Optional[bool] = None, dry_run: Optional[bool] = None) -> None:
    """Set (or with ``None`` clear) the in-process overrides."""
    global _enabled_override, _dry_run_override
    with _lock:
        _enabled_override = enabled
        _dry_run_override = dry_run


@contextmanager
def override(*, enabled: Optional[bool] = None, dry_run: Optional[bool] = None) -> Iterator[None]:
    """Temporarily force the flags (tests, benchmarks)."""
    global _enabled_override, _dry_run_override
    with _lock:
        previous = (_enabled_override, _dry_run_override)
        _enabled_override, _dry_run_override = enabled, dry_run
    try:
        yield
    finally:
        with _lock:
            _enabled_override, _dry_run_override = previous


def describe() -> str:
    if not enabled():
        return "Computer control is off (set JARVIS_COMPUTER_CONTROL=1 to enable it)."
    return "Computer control is on" + (" in dry-run mode (nothing is executed)." if dry_run() else ".")
