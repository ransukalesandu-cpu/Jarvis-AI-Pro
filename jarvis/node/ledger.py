"""The node's durable job ledger: the single source of truth for remote jobs.

Layout (in the node's state folder, never the repository)::

    ledger.json      latest snapshot of every kept job, replaced atomically
    journal.jsonl    append-only, fsynced event log (submit, claim, finish, cancel...)

Guarantees, all covered by tests:

* **Idempotent submit** — the same (submitter, idempotency key) returns the job
  that already exists; reusing a key for a *different* request is refused.
* **Leases** — a worker claims a job with a lease (holder, epoch, expiry) and must
  renew it. Every claim increments the epoch, so a late answer from an earlier
  claim (``complete`` / ``renew`` with an old epoch or holder) is rejected.
* **Restart recovery** — a job found ``running`` when the ledger is opened belongs
  to a process that no longer exists. It is re-queued only when its kind is
  idempotent and attempts remain; otherwise it ends ``interrupted`` and is
  reported, never silently re-run.
* **Deadlines** — a job that is not finished by its deadline ends ``expired``.
* **Scoping** — a device sees and cancels only the jobs it submitted.

Strings pass through :func:`jarvis.agent.store.redact` before they are stored.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from jarvis.node import protocol
from jarvis.node.protocol import JobSpec, ProtocolError, TERMINAL_STATES

MAX_KEPT_TERMINAL = 500
MAX_ACTIVE = 200
_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def _redact(text: str, limit: int = protocol.MAX_MESSAGE_CHARS) -> str:
    try:
        from jarvis.agent.store import redact
        return redact(text, limit)
    except Exception:
        return str(text or "")[:limit]


@dataclass
class JobRecord:
    id: str
    submitter: str
    kind: str
    capability: str
    idempotency_key: str
    fingerprint: str
    payload: dict
    priority: str
    privacy: str
    deadline_at: float
    state: str = "queued"
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    attempts: int = 0
    max_attempts: int = 1
    idempotent: bool = False
    lease_epoch: int = 0
    lease_holder: str = ""
    lease_expires: float = 0.0
    cancel_requested: bool = False
    progress: Optional[float] = None
    message: str = ""
    error: str = ""
    result: Optional[dict] = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def view(self, node_id: str, *, with_result: bool = False) -> dict:
        out = {
            "id": self.id, "kind": self.kind, "state": self.state, "node_id": node_id,
            "lease_epoch": self.lease_epoch, "attempts": self.attempts, "created": self.created,
            "started": self.started, "finished": self.finished, "progress": self.progress,
            "message": self.message, "error": self.error,
        }
        if with_result:
            out["result"] = self.result
        return out


class Ledger:
    def __init__(self, state_dir: Path, *, kind_policy: Callable[[str], tuple[bool, int]] | None = None,
                 clock: Callable[[], float] = time.time):
        """``kind_policy(kind) -> (idempotent, max_attempts)``; unknown kinds are refused at submit."""
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.dir / "ledger.json"
        self.journal_path = self.dir / "journal.jsonl"
        self._kind_policy = kind_policy or (lambda _kind: (False, 1))
        self._clock = clock
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._jobs: dict[str, JobRecord] = {}
        self._load()
        self._recover_after_restart()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            rows = json.loads(self.snapshot_path.read_text(encoding="utf-8")).get("jobs", [])
        except (OSError, ValueError, AttributeError):
            # A damaged snapshot is kept for the owner to inspect, never silently overwritten.
            self.snapshot_path.replace(self.snapshot_path.with_suffix(f".damaged-{int(self._clock())}"))
            self._journal({"event": "snapshot_damaged"})
            return
        known = set(JobRecord.__dataclass_fields__)
        for row in rows:
            if isinstance(row, dict) and set(row) <= known:
                try:
                    record = JobRecord(**row)
                    self._jobs[record.id] = record
                except TypeError:
                    continue

    def _save(self) -> None:
        tmp = self.snapshot_path.with_suffix(".tmp")
        data = {"version": 1, "jobs": [asdict(j) for j in self._jobs.values()]}
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.snapshot_path)

    def _journal(self, event: dict) -> None:
        line = json.dumps({"t": round(self._clock(), 3), **event}, separators=(",", ":"))
        fd = os.open(str(self.journal_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _commit(self, event: dict) -> None:
        self._journal(event)
        self._prune()
        self._save()
        self._changed.notify_all()

    def _prune(self) -> None:
        done = sorted((j for j in self._jobs.values() if j.terminal), key=lambda j: j.finished or j.created)
        for job in done[:-MAX_KEPT_TERMINAL] if len(done) > MAX_KEPT_TERMINAL else []:
            del self._jobs[job.id]

    # ── recovery ─────────────────────────────────────────────────────────────
    def _recover_after_restart(self) -> None:
        with self._lock:
            changed = False
            for job in self._jobs.values():
                if job.state == "running":
                    self._release_lost_lease(job, "the node restarted while this job was running")
                    changed = True
            if changed:
                self._commit({"event": "recovered"})

    def _release_lost_lease(self, job: JobRecord, why: str) -> None:
        job.lease_holder, job.lease_expires = "", 0.0
        if job.cancel_requested:
            self._finish(job, "cancelled", error="")
        elif job.idempotent and job.attempts < job.max_attempts:
            job.state, job.message, job.progress = "queued", f"Re-queued: {why}.", None
        else:
            self._finish(job, "interrupted", error=f"Not re-run automatically: {why}.")

    def _finish(self, job: JobRecord, state: str, *, error: str = "", result: dict | None = None) -> None:
        job.state, job.finished = state, self._clock()
        job.lease_holder, job.lease_expires = "", 0.0
        job.error = _redact(error)
        if result is not None:
            job.result = result

    # ── submitter API ────────────────────────────────────────────────────────
    def submit(self, spec: JobSpec, submitter: str) -> tuple[JobRecord, bool]:
        """Return (job, created). Re-submitting the same request returns the same job."""
        idempotent, max_attempts = self._kind_policy(spec.kind)
        fingerprint = spec.fingerprint()
        with self._lock:
            for job in self._jobs.values():
                if job.submitter == submitter and job.idempotency_key == spec.idempotency_key:
                    if job.fingerprint != fingerprint:
                        raise ProtocolError("this idempotency key was already used for a different job")
                    return job, False
            if sum(1 for j in self._jobs.values() if not j.terminal) >= MAX_ACTIVE:
                raise ProtocolError("the node's queue is full")
            now = self._clock()
            job = JobRecord(
                id=f"job_{uuid.uuid4().hex}", submitter=submitter, kind=spec.kind,
                capability=spec.capability, idempotency_key=spec.idempotency_key,
                fingerprint=fingerprint, payload=spec.payload, priority=spec.priority,
                privacy=spec.privacy, deadline_at=now + spec.deadline_s, created=now,
                idempotent=bool(idempotent), max_attempts=max(1, int(max_attempts)),
            )
            self._jobs[job.id] = job
            self._commit({"event": "submit", "job": job.id, "kind": job.kind, "by": submitter})
            return job, True

    def get(self, job_id: str, submitter: str | None = None) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or (submitter is not None and job.submitter != submitter):
                return None
            return job

    def list(self, submitter: str | None = None, limit: int = 20) -> list[JobRecord]:
        with self._lock:
            rows = [j for j in self._jobs.values() if submitter is None or j.submitter == submitter]
        return sorted(rows, key=lambda j: j.created, reverse=True)[:max(1, min(limit, 100))]

    def request_cancel(self, job_id: str, submitter: str) -> JobRecord | None:
        with self._lock:
            job = self.get(job_id, submitter)
            if job is None or job.terminal:
                return job
            if job.state == "queued":
                self._finish(job, "cancelled")
            else:
                job.cancel_requested = True
            self._commit({"event": "cancel", "job": job.id, "by": submitter})
            return job

    def counts(self) -> tuple[int, int]:
        with self._lock:
            running = sum(1 for j in self._jobs.values() if j.state == "running")
            queued = sum(1 for j in self._jobs.values() if j.state == "queued")
        return running, queued

    # ── worker API ───────────────────────────────────────────────────────────
    def claim(self, holder: str, lease_s: float, kinds: set[str] | None = None) -> JobRecord | None:
        """Take the next queued job (priority, then age) under a fresh lease."""
        with self._lock:
            self.sweep()
            queued = [j for j in self._jobs.values()
                      if j.state == "queued" and (kinds is None or j.kind in kinds)]
            if not queued:
                return None
            job = min(queued, key=lambda j: (_PRIORITY_ORDER.get(j.priority, 1), j.created))
            now = self._clock()
            job.state, job.started = "running", job.started or now
            job.attempts += 1
            job.lease_epoch += 1
            job.lease_holder, job.lease_expires = holder, now + lease_s
            job.message, job.progress = "", None
            self._commit({"event": "claim", "job": job.id, "epoch": job.lease_epoch, "holder": holder})
            return job

    def _holds(self, job: JobRecord | None, holder: str, epoch: int) -> bool:
        return (job is not None and job.state == "running" and job.lease_holder == holder
                and job.lease_epoch == epoch)

    def renew(self, job_id: str, holder: str, epoch: int, lease_s: float, *,
              progress: float | None = None, message: str | None = None) -> str:
        """Extend a lease. Returns 'ok', 'cancel' (stop now) or 'lost' (stale claim)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not self._holds(job, holder, epoch):
                return "lost"
            job.lease_expires = self._clock() + lease_s
            if progress is not None:
                job.progress = min(1.0, max(0.0, float(progress)))
            if message is not None:
                job.message = _redact(message)
            if job.cancel_requested:
                return "cancel"
            if self._clock() > job.deadline_at:
                return "expire"
            return "ok"

    def complete(self, job_id: str, holder: str, epoch: int, *, state: str,
                 result: dict | None = None, error: str = "") -> bool:
        """Record the outcome of a claim. A stale claim (old epoch/holder) is rejected."""
        if state not in TERMINAL_STATES or state == "interrupted":
            raise ValueError(f"bad final state {state!r}")
        if result is not None and protocol.json_size(result) > protocol.MAX_RESULT_BYTES:
            result, state, error = None, "failed", "The result was larger than the allowed size."
        with self._lock:
            job = self._jobs.get(job_id)
            if not self._holds(job, holder, epoch):
                self._journal({"event": "stale_result_rejected", "job": job_id, "epoch": epoch})
                return False
            if job.cancel_requested and state == "succeeded":
                state = "cancelled"        # the owner asked to stop; do not report a success
            self._finish(job, state, error=error, result=result if state == "succeeded" else None)
            self._commit({"event": "finish", "job": job.id, "state": state, "epoch": epoch})
            return True

    def sweep(self) -> list[str]:
        """Expire leases and deadlines. Returns the ids that changed."""
        changed = []
        with self._lock:
            now = self._clock()
            for job in self._jobs.values():
                if job.terminal:
                    continue
                if now > job.deadline_at:
                    self._finish(job, "expired", error="The job did not finish before its deadline.")
                    changed.append(job.id)
                elif job.state == "running" and job.lease_expires and now > job.lease_expires:
                    self._release_lost_lease(job, "its worker stopped answering")
                    changed.append(job.id)
            if changed:
                self._commit({"event": "sweep", "jobs": changed})
        return changed

    def wait_for_change(self, timeout: float) -> None:
        with self._changed:
            self._changed.wait(timeout)
