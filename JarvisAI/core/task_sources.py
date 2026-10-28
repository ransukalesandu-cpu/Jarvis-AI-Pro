"""Background producers that keep the HUD's task panels in sync with reality.

Until now only *voice commands* produced task panels: a tool call opened a card,
finished, and the card retired. But two real, already-existing parts of the app
have state the user should see while it happens, without opening the dashboard:

* **reminders** — the next pending prospective intention, from
  :mod:`memory.prospective_memory`;
* **game downloads** — Steam's own app-manifest state, the same source
  ``actions/game_updater._get_download_status`` reads.

Each producer is a plain function returning a :class:`SourceTask` or ``None``.
This module holds no Qt and no timers: the HUD polls the registry off the UI
thread and diffs the result, which keeps the whole thing testable with fakes.

Truthfulness rules
------------------
* A producer returns ``None`` when it has nothing to show. It never invents a
  placeholder row to fill the panel.
* ``progress`` is ``None`` for anything whose real fraction is unknown. Steam
  reports a state, not a percentage, so downloads are indeterminate.
* A producer that raises is *unavailable*, not empty: :meth:`TaskSourceRegistry.
  scan` records the failure in ``errors`` and omits the robot's task, so a
  broken reminder store cannot silently claim "nothing due".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

__all__ = [
    "SourceTask",
    "reminder_task",
    "download_task",
    "TaskSourceRegistry",
    "default_sources",
]


@dataclass(frozen=True)
class SourceTask:
    """One panel-worthy fact produced by a real subsystem.

    ``key`` is stable across polls so the HUD can update a panel in place
    instead of tearing it down and re-creating it every few seconds.
    """

    key: str
    kind: str            # matches ui.task_panels.TaskKind
    title: str
    subtitle: str = ""
    detail: str = ""
    progress: float | None = None
    playing: bool = False
    source: str = ""
    #: ``"waiting"`` for something scheduled but not happening yet (a reminder),
    #: ``"running"`` for work in progress (a download). The panel draws its
    #: progress bar only for ``running``, so the state must be honest.
    state: str = "running"


def reminder_task(rows: list[dict] | None = None) -> SourceTask | None:
    """The soonest pending reminder, or ``None`` when nothing is pending."""
    if rows is None:
        from memory.prospective_memory import pending_intentions

        rows = pending_intentions()

    pending = [row for row in rows or [] if isinstance(row, dict)]
    if not pending:
        return None

    first = pending[0]
    text = " ".join(str(first.get("content", "") or "").split())
    if not text:
        return None

    trigger_type = str(first.get("trigger_type", "") or "")
    trigger = str(first.get("trigger", "") or "")
    if trigger_type == "time" and trigger:
        when = _friendly_time(trigger)
    elif trigger_type == "event" and trigger:
        when = f"when {trigger}"
    elif trigger_type == "project_state" and trigger:
        when = f"when {trigger}"
    else:
        when = "pending"

    extra = len(pending) - 1
    subtitle = when if not extra else f"{when}  ·  +{extra} more"
    return SourceTask(
        key="source:reminder",
        kind="reminder",
        title=text[:80],
        subtitle=subtitle[:80],
        detail=f"{len(pending)} pending intention(s)",
        progress=None,
        source="memory.prospective_memory",
        # Nothing is happening yet: it is scheduled, not running.
        state="waiting",
    )


def _friendly_time(iso: str) -> str:
    """``2026-10-29T09:00`` → ``29 Oct 09:00`` (falls back to the raw string)."""
    from datetime import datetime

    try:
        moment = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return str(iso)[:32]
    return moment.strftime("%d %b %H:%M")


def download_task(scan: Callable[[], dict] | None = None) -> SourceTask | None:
    """Active Steam downloads/updates, or ``None`` when there are none.

    ``scan`` may be injected; by default it reads Steam's manifest state through
    ``actions.game_updater``. Steam's state is a flag (downloading / queued), so
    ``progress`` stays ``None`` — the panel shows an indeterminate sweep rather
    than a fabricated percentage.
    """
    if scan is None:
        scan = _scan_steam_downloads
    try:
        info = scan() or {}
    except Exception:
        raise

    active = [str(name) for name in info.get("active", []) if str(name).strip()]
    pending = [str(name) for name in info.get("pending", []) if str(name).strip()]
    if not active and not pending:
        return None

    if active:
        title = active[0]
        subtitle = "DOWNLOADING"
        if len(active) > 1:
            subtitle = f"DOWNLOADING · +{len(active) - 1} more"
        key = "source:download"
    else:
        title = pending[0]
        subtitle = f"UPDATE QUEUED · {len(pending)} waiting" if len(pending) > 1 else "UPDATE QUEUED"
        key = "source:download"

    return SourceTask(
        key=key,
        kind="download",
        title=title[:80],
        subtitle=subtitle[:80],
        detail="Steam manifest state",
        progress=None,
        source="actions.game_updater",
    )


def _scan_steam_downloads() -> dict:
    """Read Steam's manifest state, or ``{}`` when Steam is not installed.

    Imported lazily: ``game_updater`` pulls in pyautogui/comtypes and is slow to
    import, and the HUD must not pay that cost unless Steam is actually present.
    """
    from actions import game_updater

    steam_path = game_updater._find_steam_path()
    if steam_path is None:
        return {}
    games = game_updater._get_steam_games(steam_path)
    return {
        "active": [g["name"] for g in games if g.get("state") == 1026],
        "pending": [g["name"] for g in games if g.get("state") in (6, 516)],
    }


class TaskSourceRegistry:
    """Runs the producers and returns the tasks they currently justify."""

    def __init__(self, sources: dict[str, Callable[[], SourceTask | None]] | None = None):
        self._sources = dict(sources if sources is not None else default_sources())
        self.errors: dict[str, str] = {}

    def scan(self) -> list[SourceTask]:
        """Every non-``None`` task, in a deterministic order (sorted by key)."""
        self.errors.clear()
        found: list[SourceTask] = []
        for name, source in self._sources.items():
            try:
                task = source()
            except Exception as exc:
                # A broken producer is *unavailable*: say so instead of
                # reporting an empty world.
                self.errors[name] = f"{type(exc).__name__}: {exc}"[:160]
                continue
            if task is not None:
                found.append(task)
        return sorted(found, key=lambda item: item.key)

    def names(self) -> list[str]:
        return list(self._sources)


def default_sources() -> dict[str, Callable[[], SourceTask | None]]:
    """The producer set wired into the HUD."""
    return {
        "reminders": reminder_task,
        "downloads": download_task,
    }
