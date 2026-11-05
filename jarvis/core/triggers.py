"""Proactive triggers: things that let JARVIS start a turn on its own.

A trigger is registered the same way a tool is, never hard-coded in the voice
loop:

* any ``actions/*.py`` (or plugin) module may expose ``TRIGGERS = [ {...} ]``,
  collected by ``core.action_loader.discover_actions`` at startup, and
* the owner can add one by voice through the ``schedule_trigger`` tool
  (``actions/proactive_triggers.py``); those are saved in the user data folder
  and survive a restart.

Trigger fields (all optional except ``name`` and one schedule)::

    {
        "name": "morning_briefing",
        "prompt": "Give me my morning briefing.",   # text injected as the turn
        "daily_at": "07:30",                       # local HH:MM, every day
        "every_seconds": 3600,                     # or a fixed interval
        "once_at": 1767000000.0,                   # or one time (epoch seconds)
        "check": callable,                         # or a condition: () -> prompt | None
        "respect_quiet_hours": True,
        "description": "...",
    }

The scheduler (``BackgroundServicesMixin._run_trigger_scheduler``) asks
:meth:`TriggerRegistry.due` once per tick and injects each due prompt through
``session.send_client_content`` — the SDK's supported way to start a turn.
It never fires while the owner is talking, while JARVIS is speaking or while a
turn is pending, and it holds triggers during quiet hours.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_PERSISTED_FIELDS = ("name", "prompt", "description", "daily_at", "every_seconds",
                     "once_at", "respect_quiet_hours", "enabled", "cron", "tz",
                     "catch_up", "mode", "max_per_hour", "consecutive_failures")
MAX_CONSECUTIVE_FAILURES = 3
CATCH_UP_GRACE_SECONDS = 120.0
MODES = ("turn", "task")
CATCH_UP_MODES = ("once", "skip")


@dataclass
class Trigger:
    name: str
    prompt: str = ""
    description: str = ""
    daily_at: Optional[str] = None
    every_seconds: Optional[float] = None
    once_at: Optional[float] = None
    cron: Optional[str] = None      # 5-field cron expression (core/cron_expr.py)
    tz: Optional[str] = None        # IANA zone for cron/daily_at; local when empty
    catch_up: str = "once"          # missed slot: "once" fire late, or "skip" it
    mode: str = "turn"              # "turn" speaks a prompt; "task" runs a background agent task
    max_per_hour: int = 12          # budget: fires beyond this in an hour are held
    consecutive_failures: int = 0
    run_requested: bool = False     # "run now": fires on the next scheduler tick (not saved)
    check: Optional[Callable[[], Optional[str]]] = None
    respect_quiet_hours: bool = True
    enabled: bool = True
    source: str = "file"            # "file" (discovered) or "user" (saved by voice)
    last_fired: float = 0.0         # wall-clock epoch seconds
    registered_at: float = field(default_factory=time.time)

    def validate(self) -> None:
        if not _NAME_RE.match(self.name or ""):
            raise ValueError("trigger name must be an identifier (letters, digits, _)")
        schedules = [self.daily_at is not None, self.every_seconds is not None,
                     self.once_at is not None, self.cron is not None, self.check is not None]
        if sum(schedules) != 1:
            raise ValueError(
                "a trigger needs exactly one of daily_at, every_seconds, once_at, cron, check")
        if self.mode not in MODES:
            raise ValueError("mode must be 'turn' or 'task'")
        if self.catch_up not in CATCH_UP_MODES:
            raise ValueError("catch_up must be 'once' or 'skip'")
        if int(self.max_per_hour) < 1:
            raise ValueError("max_per_hour must be at least 1")
        if self.cron is not None:
            from jarvis.core import cron_expr
            try:
                cron_expr.parse(self.cron)
                cron_expr.resolve_zone(self.tz)
            except cron_expr.CronError as exc:
                raise ValueError(str(exc)) from exc
        elif self.tz:
            from jarvis.core import cron_expr
            try:
                cron_expr.resolve_zone(self.tz)
            except cron_expr.CronError as exc:
                raise ValueError(str(exc)) from exc
        if self.daily_at is not None and not _HHMM_RE.match(str(self.daily_at)):
            raise ValueError("daily_at must be HH:MM (24-hour)")
        if self.every_seconds is not None and float(self.every_seconds) < 30:
            raise ValueError("every_seconds must be at least 30")
        if self.check is None and not str(self.prompt or "").strip():
            raise ValueError("a scheduled trigger needs a prompt")

    def next_due(self, now: float) -> Optional[float]:
        """Epoch time this trigger is next due, or None if it never will be."""
        if not self.enabled or self.check is not None:
            return None
        if self.once_at is not None:
            return None if self.last_fired else float(self.once_at)
        if self.cron is not None:
            from jarvis.core import cron_expr
            expr = cron_expr.parse(self.cron)
            base = self.last_fired or self.registered_at
            due = cron_expr.next_after(expr, base, self.tz)
            if due is not None and self.catch_up == "skip" and due < now - CATCH_UP_GRACE_SECONDS:
                due = cron_expr.next_after(expr, now - CATCH_UP_GRACE_SECONDS, self.tz)
            return due
        if self.every_seconds is not None:
            base = self.last_fired or self.registered_at
            return base + float(self.every_seconds)
        hh, mm = (int(x) for x in str(self.daily_at).split(":"))
        today = datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        candidate = today.timestamp()
        if self.last_fired and self.last_fired >= candidate:
            candidate = (today + timedelta(days=1)).timestamp()
        elif not self.last_fired and self.registered_at > candidate:
            # Registered after today's slot: first run is tomorrow, not "late now".
            candidate = (today + timedelta(days=1)).timestamp()
        if self.catch_up == "skip" and candidate < now - CATCH_UP_GRACE_SECONDS:
            candidate = (today + timedelta(days=1)).timestamp()
        return candidate


def parse_quiet_hours(value: str | None) -> Optional[tuple[int, int]]:
    """'22:00-07:00' -> (1320, 420) minutes after midnight; None when unset/invalid."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        start, end = (part.strip() for part in text.split("-", 1))
        m1, m2 = _HHMM_RE.match(start), _HHMM_RE.match(end)
        if not (m1 and m2):
            return None
        return int(m1[1]) * 60 + int(m1[2]), int(m2[1]) * 60 + int(m2[2])
    except ValueError:
        return None


def in_quiet_hours(quiet: Optional[tuple[int, int]], when: datetime) -> bool:
    if not quiet:
        return False
    start, end = quiet
    minute = when.hour * 60 + when.minute
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end      # window crosses midnight


class TriggerRegistry:
    """All known triggers; user-created ones are persisted to ``store_path``."""

    def __init__(self, store_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._triggers: dict[str, Trigger] = {}
        self._store_path = store_path
        self._fires: dict[str, list[float]] = {}     # recent fire times, for max_per_hour
        if store_path is not None:
            self._load()

    # ── registration ──────────────────────────────────────────────────────────
    def register(self, trigger: Trigger | dict, *, source: str | None = None,
                 persist: bool = False) -> Trigger:
        if isinstance(trigger, dict):
            known = {k: v for k, v in trigger.items() if k in Trigger.__dataclass_fields__}
            trigger = Trigger(**known)
        if source:
            trigger.source = source
        trigger.validate()
        with self._lock:
            existing = self._triggers.get(trigger.name)
            if existing is not None and existing.source != trigger.source and existing.source == "file":
                raise ValueError(f"trigger '{trigger.name}' is defined by a file and cannot be replaced")
            if existing is not None:
                trigger.last_fired = max(trigger.last_fired, existing.last_fired)
            self._triggers[trigger.name] = trigger
            if persist:
                self._save()
        return trigger

    def unregister(self, name: str) -> bool:
        with self._lock:
            trig = self._triggers.get(name)
            if trig is None or trig.source != "user":
                return False
            del self._triggers[name]
            self._save()
            return True

    def get(self, name: str) -> Optional[Trigger]:
        with self._lock:
            return self._triggers.get(name)

    def list(self) -> list[Trigger]:
        with self._lock:
            return sorted(self._triggers.values(), key=lambda t: t.name)

    # ── scheduling ────────────────────────────────────────────────────────────
    def due(self, now: Optional[float] = None, *, quiet_hours: str | None = None,
            ) -> list[tuple[Trigger, str]]:
        """Triggers that should fire now, with the prompt to inject.

        A trigger held by quiet hours stays due and fires when they end
        (a 07:30 reminder during 22:00-08:00 quiet hours fires at 08:00).
        """
        now = time.time() if now is None else now
        quiet = parse_quiet_hours(quiet_hours)
        quiet_now = in_quiet_hours(quiet, datetime.fromtimestamp(now))
        ready: list[tuple[Trigger, str]] = []
        with self._lock:
            triggers = list(self._triggers.values())
        for trig in triggers:
            if not trig.enabled or (quiet_now and trig.respect_quiet_hours):
                continue
            if self._over_budget(trig, now):
                continue
            if trig.run_requested and trig.check is None and trig.prompt:
                trig.run_requested = False
                ready.append((trig, trig.prompt))
                continue
            if trig.check is not None:
                try:
                    text = trig.check()
                except Exception as exc:     # a broken condition never stops the loop
                    print(f"[Triggers] '{trig.name}' check failed: {type(exc).__name__}: {exc}")
                    continue
                if text:
                    ready.append((trig, str(text)))
                continue
            due_at = trig.next_due(now)
            if due_at is not None and due_at <= now:
                ready.append((trig, trig.prompt))
        return ready

    def _over_budget(self, trig: Trigger, now: float) -> bool:
        with self._lock:
            recent = [t for t in self._fires.get(trig.name, []) if now - t < 3600]
            self._fires[trig.name] = recent
            return len(recent) >= int(trig.max_per_hour)

    def request_run(self, name: str) -> bool:
        """Ask the scheduler to run a trigger on its next tick (ignores the schedule)."""
        with self._lock:
            trig = self._triggers.get(name)
            if trig is None or trig.check is not None:
                return False
            trig.run_requested = True
            return True

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with self._lock:
            trig = self._triggers.get(name)
            if trig is None:
                return False
            trig.enabled = bool(enabled)
            if enabled:
                trig.consecutive_failures = 0
            if trig.source == "user":
                self._save()
            return True

    def record_result(self, name: str, ok: bool) -> bool:
        """Count a run outcome. Returns True when this failure auto-disabled the trigger."""
        with self._lock:
            trig = self._triggers.get(name)
            if trig is None:
                return False
            if ok:
                trig.consecutive_failures = 0
                disabled = False
            else:
                trig.consecutive_failures += 1
                disabled = trig.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                if disabled:
                    trig.enabled = False
            if trig.source == "user":
                self._save()
            return disabled

    def mark_fired(self, name: str, when: Optional[float] = None) -> None:
        with self._lock:
            trig = self._triggers.get(name)
            if trig is None:
                return
            trig.last_fired = time.time() if when is None else when
            self._fires.setdefault(name, []).append(trig.last_fired)
            if trig.once_at is not None and trig.source == "user":
                # A one-shot reminder is finished once it has been delivered.
                del self._triggers[name]
            if trig.source == "user":
                self._save()

    # ── persistence (user triggers only) ─────────────────────────────────────
    def _load(self) -> None:
        path = self._store_path
        if path is None or not path.exists():
            return
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[Triggers] Could not read {path.name}: {exc}")
            return
        for row in rows if isinstance(rows, list) else []:
            try:
                trig = Trigger(**{k: row[k] for k in (*_PERSISTED_FIELDS, "last_fired",
                                                      "registered_at") if k in row})
                trig.source = "user"
                trig.validate()
                self._triggers[trig.name] = trig
            except (TypeError, ValueError) as exc:
                print(f"[Triggers] Skipped a saved trigger: {exc}")

    def _save(self) -> None:
        path = self._store_path
        if path is None:
            return
        rows = []
        for trig in self._triggers.values():
            if trig.source != "user":
                continue
            row = {k: v for k, v in asdict(trig).items()
                   if k in (*_PERSISTED_FIELDS, "last_fired", "registered_at")}
            rows.append(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        tmp.replace(path)


_REGISTRY: Optional[TriggerRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_trigger_registry() -> TriggerRegistry:
    """The process-wide registry, backed by <user data>/triggers.json."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            from jarvis.core.user_data import user_data_file
            _REGISTRY = TriggerRegistry(user_data_file("triggers.json"))
        return _REGISTRY


def reset_trigger_registry_for_tests(registry: Optional[TriggerRegistry] = None) -> None:
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = registry
