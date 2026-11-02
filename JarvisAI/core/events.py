"""A lightweight event hook that owner rules listen to.

Anything can report an event: ``emit("email", {"from": ..., "subject": ...})``.
Every enabled rule (core/owner_store.RuleStore) whose ``source`` matches and
whose conditions all match the payload fires its action. Rules are not tied to
an app: the email tool, the email watcher, the schedule, the file watcher and
any plugin all use the same call.

A condition is ``{field: text}``: the payload's field must contain the text
(case-insensitive). The special field ``text`` matches any field. An empty
condition set matches every event from that source.

The live session installs the executor that performs actions
(JarvisLive._execute_rule_action); without one, matches are only recorded.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

_lock = threading.Lock()
_listeners: list[Callable[[str, dict], Any]] = []
_executor: Optional[Callable[[dict, str, dict], Any]] = None


def subscribe(listener: Callable[[str, dict], Any]) -> None:
    """Hear every event (source, payload); for plugins that react to events."""
    with _lock:
        _listeners.append(listener)


def set_rule_executor(executor: Optional[Callable[[dict, str, dict], Any]]) -> None:
    global _executor
    with _lock:
        _executor = executor


def _matches(conditions: dict, payload: dict) -> bool:
    for field, needle in (conditions or {}).items():
        needle = str(needle).casefold()
        if field in ("text", "*"):
            haystack = " ".join(str(v) for v in payload.values())
        else:
            haystack = str(payload.get(field, ""))
        if needle not in haystack.casefold():
            return False
    return True


def matching_rules(source: str, payload: dict) -> list[dict]:
    from core.owner_store import get_owner_store
    source = str(source or "").strip().lower()
    return [r for r in get_owner_store().rules.list()
            if r["enabled"] and r["source"] in (source, "*", "any")
            and _matches(r["conditions"], payload)]


def emit(source: str, payload: dict | None = None) -> list[str]:
    """Report an event. Returns the names of the rules that fired. Never raises."""
    payload = dict(payload or {})
    with _lock:
        listeners = list(_listeners)
        executor = _executor
    for listener in listeners:
        try:
            listener(source, payload)
        except Exception as exc:
            print(f"[Events] listener failed: {type(exc).__name__}: {exc}")
    fired: list[str] = []
    try:
        from core.owner_store import get_owner_store
        rules = matching_rules(source, payload)
        store = get_owner_store()
    except Exception as exc:
        print(f"[Events] rules unavailable: {type(exc).__name__}: {exc}")
        return fired
    for rule in rules:
        try:
            if executor is not None:
                executor(rule, source, payload)
            store.rules.mark_fired(rule["name"])
            fired.append(rule["name"])
        except Exception as exc:
            print(f"[Events] rule '{rule['name']}' failed: {type(exc).__name__}: {exc}")
    return fired


def reset_for_tests() -> None:
    global _executor
    with _lock:
        _listeners.clear()
        _executor = None
