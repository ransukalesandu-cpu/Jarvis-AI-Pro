"""Background jobs: slow work that must not block the conversation.

A long-running tool (``"long_running": True``) or the ``start_job`` tool
starts a job and gets an id back at once. JARVIS says the job has started;
when it finishes, :class:`JobManager` calls ``on_done`` and the live session
announces the result through the same path proactive triggers use, so it
never talks over the owner.

Jobs run as asyncio tasks on the live loop. Blocking work inside a job goes
through ``asyncio.to_thread``. ``cancel`` stops the task; work already running
in a thread is told through ``job.cancel_event`` and should check it.
"""
from __future__ import annotations

import asyncio
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from core import failsoft

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


class JobManager:
    MAX_KEPT = 50

    def __init__(self, on_done: Callable[[Job], Any] | None = None):
        self._jobs: dict[str, Job] = {}
        self._on_done = on_done

    def set_on_done(self, callback: Callable[[Job], Any] | None) -> None:
        self._on_done = callback

    def start(self, name: str, work: Callable[[Job], Awaitable[Any]],
              description: str = "") -> Job:
        """Start ``work(job)`` as a task on the running loop and return the job."""
        job = Job(id=f"job{next(_ids)}", name=name, description=description)
        self._jobs[job.id] = job
        job.task = asyncio.get_running_loop().create_task(self._run(job, work))
        self._prune()
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
            from core.tool_runtime import speakable_error
            job.status = "failed"
            job.result = speakable_error(job.name, exc)
        finally:
            job.finished = time.time()
            try:
                from core import action_log
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
