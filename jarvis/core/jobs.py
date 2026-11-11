"""Background jobs: slow work that must not block the conversation.

A long-running tool (``"long_running": True``) or the ``start_job`` tool
starts a job and gets an id back at once. JARVIS says the job has started;
when it finishes, :class:`JobManager` calls ``on_done`` and the live session
announces the result through the same path proactive triggers use, so it
never talks over the owner.

Jobs run as asyncio tasks on the live loop. Blocking work inside a job goes
through ``asyncio.to_thread``. ``cancel`` stops the task; work already running
in a thread is told through ``job.cancel_event`` and should check it.

**Sources.** Other engines with their own lifecycle (the autonomous agent's
TaskRunner, ``agent/jobs_source.py``) register a :class:`JobSource` instead of
being wrapped in fake jobs. Their rows appear in :meth:`JobManager.snapshot`
(the web UI Jobs window), :meth:`running_ids` and :meth:`summaries` (the
``job_status`` voice tool), and cancelling one of their ids is delegated to the
source. They keep their own announcements, so nothing is spoken twice.
``cancel_all`` touches only this manager's own jobs; the stop word stops the
other engines itself.
"""
from __future__ import annotations

import asyncio
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from jarvis.core import failsoft

_ids = itertools.count(1)


@dataclass
class Job:
    id: str
    name: str
    description: str = ""
    status: str = "running"          # running | done | failed | cancelled
    result: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event)
    task: Optional[asyncio.Task] = None

    def summary(self) -> str:
        elapsed = (self.finished or time.time()) - self.started
        text = f"Job {self.id} ({self.name}) is {self.status} after {elapsed:.0f}s"
        if self.status != "running" and self.result:
            text += f": {self.result[:300]}"
        return text + "."


#: Statuses a row can have: this manager's own jobs use the first four; sources
#: may also report "waiting" (e.g. for approval) and "paused".
JOB_STATUSES = ("running", "done", "failed", "cancelled", "waiting", "paused")
ACTIVE_STATUSES = frozenset({"running", "waiting", "paused"})


class JobSource(Protocol):
    """Another engine's work shown alongside the jobs. Methods must be cheap (no I/O)."""

    def rows(self) -> list[dict]: ...          # {"id","name","status","started","finished"}
    def owns(self, job_id: str) -> bool: ...
    def cancel(self, job_id: str) -> bool: ...  # any thread


class JobManager:
    MAX_KEPT = 50
    MAX_ROWS = 20

    def __init__(self, on_done: Callable[[Job], Any] | None = None):
        self._jobs: dict[str, Job] = {}
        self._on_done = on_done
        self._listeners: list[Callable[[], None]] = []
        self._sources: list[JobSource] = []

    def add_source(self, source: JobSource) -> Callable[[], None]:
        """Show ``source``'s rows with the jobs. Returns an unsubscribe."""
        if source not in self._sources:
            self._sources.append(source)
        self._notify()

        def remove() -> None:
            if source in self._sources:
                self._sources.remove(source)
                self._notify()
        return remove

    def notify(self) -> None:
        """For sources: something changed, refresh every display."""
        self._notify()

    def _source_rows(self) -> list[dict]:
        rows: list[dict] = []
        for source in list(self._sources):
            try:
                for row in source.rows():
                    if row.get("status") in JOB_STATUSES:
                        rows.append(row)
            except Exception:
                failsoft.suppress("core.jobs:source_rows")
        return rows

    def _source_for(self, job_id: str) -> Optional[JobSource]:
        job_id = str(job_id).strip()
        if job_id in self._jobs:
            return None
        for source in list(self._sources):
            try:
                if source.owns(job_id):
                    return source
            except Exception:
                failsoft.suppress("core.jobs:source_owns")
        return None

    def running_ids(self) -> list[str]:
        """Ids that can still be cancelled: own running jobs plus active source rows."""
        return ([j.id for j in self.running()]
                + [str(r["id"]) for r in self._source_rows() if r["status"] in ACTIVE_STATUSES])

    def summaries(self, limit: int = 10) -> list[str]:
        """One sentence per newest job or source row (for the job_status voice tool)."""
        now = time.time()
        items = [(j.started, j.summary()) for j in self.list()]
        for row in self._source_rows():
            elapsed = (row.get("finished") or now) - float(row.get("started") or now)
            items.append((float(row.get("started") or 0.0),
                          f"{row['name']} ({row['id']}) is {row['status']} after {elapsed:.0f}s."))
        return [text for _, text in sorted(items, key=lambda item: item[0], reverse=True)[:limit]]

    def add_listener(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Call ``fn()`` (from whichever thread changed things) whenever a job starts or ends. Returns an unsubscribe."""
        self._listeners.append(fn)

        def remove() -> None:
            if fn in self._listeners:
                self._listeners.remove(fn)
        return remove

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                failsoft.suppress("core.jobs:listener")

    def snapshot(self) -> list[dict]:
        """Plain, result-free view of the newest jobs for a display: id, name, status, start/finish (epoch seconds).

        Includes source rows (e.g. autonomous tasks), newest first, at most MAX_ROWS."""
        rows = [{"id": j.id, "name": j.name, "status": j.status, "started": j.started, "finished": j.finished or None}
                for j in self.list()[:self.MAX_ROWS]]
        for row in self._source_rows():
            rows.append({"id": str(row["id"]), "name": str(row["name"]), "status": row["status"],
                         "started": float(row["started"]), "finished": row.get("finished") or None})
        rows.sort(key=lambda r: r["started"], reverse=True)
        return rows[:self.MAX_ROWS]

    def request_cancel(self, job_id: str) -> bool:
        """Like :meth:`cancel` but safe to call from any thread (the task lives on the live loop)."""
        source = self._source_for(job_id)
        if source is not None:
            return bool(source.cancel(str(job_id).strip()))
        job = self.get(job_id)
        if job is None or job.status != "running":
            return False
        job.cancel_event.set()
        task = job.task
        if task is not None:
            try:
                task.get_loop().call_soon_threadsafe(task.cancel)
            except RuntimeError:        # loop already closed: nothing left to cancel
                return False
        return True

    def set_on_done(self, callback: Callable[[Job], Any] | None) -> None:
        self._on_done = callback

    def start(self, name: str, work: Callable[[Job], Awaitable[Any]],
              description: str = "") -> Job:
        """Start ``work(job)`` as a task on the running loop and return the job."""
        job = Job(id=f"job{next(_ids)}", name=name, description=description)
        self._jobs[job.id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job, work))
        self._prune()
        self._notify()
        return job

    async def _run(self, job: Job, work: Callable[[Job], Awaitable[Any]]) -> None:
        try:
            result = await work(job)
            job.result = str(result if result is not None else "Done.")
            job.status = "cancelled" if job.cancel_event.is_set() else "done"
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.result = job.result or "Cancelled."
        except Exception as exc:
            from jarvis.core.tool_runtime import speakable_error
            job.status = "failed"
            job.result = speakable_error(job.name, exc)
        finally:
            job.finished = time.time()
            self._notify()
            try:
                from jarvis.core import action_log
                action_log.record(job.name, {"job": job.id}, job.result, status=f"job_{job.status}",
                                  job_id=job.id,
                                  duration_ms=int((job.finished - job.started) * 1000))
            except Exception:
                failsoft.suppress("core.jobs:action_log")
            if self._on_done is not None and job.status != "cancelled":
                try:
                    self._on_done(job)
                except Exception as exc:
                    print(f"[Jobs] on_done failed: {type(exc).__name__}: {exc}")

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(str(job_id).strip())

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)

    def running(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status == "running"]

    def cancel(self, job_id: str) -> bool:
        source = self._source_for(job_id)
        if source is not None:
            return bool(source.cancel(str(job_id).strip()))
        job = self.get(job_id)
        if job is None or job.status != "running":
            return False
        job.cancel_event.set()
        if job.task is not None:
            job.task.cancel()
        return True

    def cancel_all(self) -> int:
        return sum(1 for job in list(self.running()) if self.cancel(job.id))

    def _prune(self) -> None:
        finished = [j for j in self.list() if j.status != "running"]
        for job in finished[self.MAX_KEPT:]:
            self._jobs.pop(job.id, None)


_MANAGER: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = JobManager()
    return _MANAGER


def reset_job_manager_for_tests(manager: Optional[JobManager] = None) -> None:
    global _MANAGER
    _MANAGER = manager
