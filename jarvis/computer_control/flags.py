"""Feature flag and dry-run switch for the Computer Control Engine.

The engine is OFF unless the owner turns it on. Precedence, highest first:

1. :func:`override` / :func:`set_overrides` — tests and benchmarks only.
2. ``JARVIS_COMPUTER_CONTROL`` / ``JARVIS_COMPUTER_CONTROL_DRY_RUN`` when set to
   anything non-empty: ``1``/``true``/``on``/``yes``/``enabled`` means on, any other
   value (e.g. ``0``) forces it off whatever the saved setting says.
3. The owner's saved setting (``computer_control_enabled`` /
   ``computer_control_dry_run`` in ``config/api_keys.json``), changed by voice through
   ``jarvis_settings`` (owner-only, confirmation banner) — see :func:`save_setting`.
4. Off.

While disabled no computer-control tool is offered to the model except
``cc_engine_status`` (which explains why), and
:class:`~jarvis.computer_control.runner.ActionRunner` refuses every action with
status ``disabled``. With dry-run on, actions are classified, approved and logged
exactly as for real, but the handler is never called.

The saved setting is read once and cached; :func:`save_setting` updates the cache
and notifies listeners (the live session re-sends its tool list). A hand edit of
the config file takes effect at the next start.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

ENV_ENABLED = "JARVIS_COMPUTER_CONTROL"
ENV_DRY_RUN = "JARVIS_COMPUTER_CONTROL_DRY_RUN"
KEY_ENABLED = "computer_control_enabled"
KEY_DRY_RUN = "computer_control_dry_run"
_TRUE = frozenset({"1", "true", "on", "yes", "enabled"})

_lock = threading.Lock()
_enabled_override: Optional[bool] = None
_dry_run_override: Optional[bool] = None
_saved: Optional[dict[str, bool]] = None          # cache of the owner's saved setting
_listeners: list[Callable[[bool, bool], None]] = []


def _env(name: str) -> Optional[bool]:
    """True/False when the variable is set (non-empty), None when it is not."""
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return None
    return raw in _TRUE


def _env_true(name: str) -> bool:
    return bool(_env(name))


def _read_saved() -> dict[str, bool]:
    """The owner's saved choice from config/api_keys.json (missing or unreadable -> off)."""
    try:
        from jarvis.memory.config_manager import load_api_keys
        data = load_api_keys()
    except Exception:
        return {KEY_ENABLED: False, KEY_DRY_RUN: False}
    data = data if isinstance(data, dict) else {}
    return {KEY_ENABLED: data.get(KEY_ENABLED) is True, KEY_DRY_RUN: data.get(KEY_DRY_RUN) is True}


def _write_saved(values: dict[str, bool]) -> None:
    from jarvis.memory.config_manager import load_api_keys, write_api_config
    data = load_api_keys()
    data = dict(data) if isinstance(data, dict) else {}
    data.update(values)
    write_api_config(data)


def _saved_value(key: str) -> bool:
    global _saved
    with _lock:
        if _saved is None:
            _saved = _read_saved()
        return bool(_saved.get(key, False))


def source() -> str:
    """Where the on/off decision comes from: "override", "environment" or "setting"."""
    with _lock:
        if _enabled_override is not None:
            return "override"
    return "environment" if _env(ENV_ENABLED) is not None else "setting"


def enabled() -> bool:
    """True only when the owner opted in."""
    with _lock:
        if _enabled_override is not None:
            return _enabled_override
    env = _env(ENV_ENABLED)
    return env if env is not None else _saved_value(KEY_ENABLED)


_effective_enabled = enabled


def dry_run() -> bool:
    with _lock:
        if _dry_run_override is not None:
            return _dry_run_override
    env = _env(ENV_DRY_RUN)
    return env if env is not None else _saved_value(KEY_DRY_RUN)


def saved_setting() -> dict[str, bool]:
    """The saved owner setting (what the environment variables would override)."""
    return {"enabled": _saved_value(KEY_ENABLED), "dry_run": _saved_value(KEY_DRY_RUN)}


def save_setting(*, enabled: Optional[bool] = None, dry_run: Optional[bool] = None) -> str:
    """Persist the owner's choice and notify listeners. Returns a sentence for the owner.

    Callers are responsible for authorization: this is reached only through
    ``jarvis_settings`` behind ``core.security.guard`` (DANGEROUS -> confirmation).
    """
    global _saved
    updates: dict[str, bool] = {}
    if enabled is not None:
        updates[KEY_ENABLED] = bool(enabled)
    if dry_run is not None:
        updates[KEY_DRY_RUN] = bool(dry_run)
    if not updates:
        return describe()
    with _lock:
        if _saved is None:
            _saved = _read_saved()
        before = dict(_saved)
    was_enabled = enabled_value_for(before)
    _write_saved(updates)                     # raises if the config cannot be written
    with _lock:
        _saved = {**before, **updates}
    enabled_now = _effective_enabled()     # `enabled` is a parameter here
    for listener in list(_listeners):
        try:
            listener(bool(was_enabled != enabled_now), enabled_now)
        except Exception:
            from jarvis.core import failsoft
            failsoft.suppress("computer_control.flags:listener")
    note = ""
    if enabled is not None and _env(ENV_ENABLED) is not None and _env(ENV_ENABLED) != bool(enabled):
        note = (f" The saved setting changed, but {ENV_ENABLED} is set in the environment and "
                "still decides; remove it for the saved setting to apply.")
    return describe() + note


def enabled_value_for(saved: dict[str, bool]) -> bool:
    """What enabled() would return with ``saved`` as the stored setting."""
    with _lock:
        if _enabled_override is not None:
            return _enabled_override
    env = _env(ENV_ENABLED)
    return env if env is not None else bool(saved.get(KEY_ENABLED, False))


def add_listener(listener: Callable[[bool, bool], None]) -> None:
    """``listener(enabled_changed, enabled)`` after every :func:`save_setting`."""
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)


def remove_listener(listener: Callable[[bool, bool], None]) -> None:
    with _lock:
        if listener in _listeners:
            _listeners.remove(listener)


def reload_saved() -> None:
    """Forget the cached setting (tests; the next read goes back to the config file)."""
    global _saved
    with _lock:
        _saved = None


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
        if source() == "environment":
            return f"Computer control is off ({ENV_ENABLED} is set to off in the environment)."
        return ("Computer control is off. The owner can turn it on with the "
                "computer_control setting (confirmation required) or JARVIS_COMPUTER_CONTROL=1.")
    return "Computer control is on" + (" in dry-run mode (nothing is executed)." if dry_run() else ".")
