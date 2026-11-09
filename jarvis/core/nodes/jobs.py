"""Submit work to a worker node and follow it honestly until it ends.

* **Placement first** — :mod:`jarvis.core.nodes.router` decides; nothing is sent when
  the answer is "blocked" or "laptop" (the laptop path needs the owner's yes and is
  wired per job type, never automatically here).
* **Idempotent submit** — each submission gets its idempotency key and is saved
  *before* it is sent. If the answer is lost (timeout, Wi-Fi drop), the retry reuses
  the key, so the node returns the job it already has instead of starting another.
* **Waiting, not failing** — while the node is unreachable the submission shows
  ``waiting_for_node``; nothing is reported as done until the node says so.
* **Stale answers rejected** — a status must name the same job id and node id, and
  its lease epoch may never go backwards.
* **Cancel propagation** — the job's cancel event and the global emergency stop
  (``computer_control.estop``) send ``job_cancel``; success is reported only after
  the node confirms.
* **Restart** — the saved submissions are re-checked, never re-sent under a new key.

Saved in ``<user data>/nodes/submissions.json`` (owner-only file). Tokens are never
stored or logged here.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from jarvis.core import failsoft
from jarvis.core.nodes import router
from jarvis.core.nodes.client import NodeRefused, NodeUnavailable
from jarvis.node import protocol
from jarvis.node.protocol import ProtocolError, TERMINAL_STATES

MAX_KEPT = 100
DEADLINE_GRACE_S = 120.0
CANCEL_GIVE_UP_S = 30.0
LOCAL_STATES = ("submitting", "waiting_for_node", "unknown")


class RoutingBlocked(RuntimeError):
    def __init__(self, placement: router.Placement):
        super().__init__(placement.reason)
        self.placement = placement


@dataclass
class Submission:
    local_id: str
    node: str
    node_id: str
    idempotency_key: str
    kind: str
    capability: str
    request: dict
    deadline_s: float
    job_id: str = ""
    state: str = "submitting"
    lease_epoch: int = 0
    attempts: int = 0
    progress: Optional[float] = None
    message: str = ""
    error: str = ""
    result: Optional[dict] = None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    cancel_requested: bool = False
    announced: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def public(self) -> dict:
        return {"id": self.local_id, "node": self.node, "kind": self.kind, "state": self.state,
                "progress": self.progress, "message": self.message, "error": self.error,
                "created": self.created, "updated": self.updated}


def _store_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    folder = user_data_dir() / "nodes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "submissions.json"


class RemoteJobs:
    def __init__(self, registry, *, path: Path | None = None, clock=time.time, sleep=time.sleep,
                 emit: Callable[[str, dict], None] | None = None):
        self.registry = registry
        self.path = Path(path) if path else _store_path()
        self._clock, self._sleep = clock, sleep
        self._emit = emit
        self._lock = threading.RLock()
        self._subs: dict[str, Submission] = {}
        self._listeners: list[Callable[[], None]] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8")).get("submissions", [])
        except (OSError, ValueError, AttributeError):
            return
        fields = set(Submission.__dataclass_fields__)
        for row in rows:
            if isinstance(row, dict) and set(row) <= fields:
                try:
                    sub = Submission(**row)
                    self._subs[sub.local_id] = sub
                except TypeError:
                    continue

    def _save(self) -> None:
        with self._lock:
            subs = sorted(self._subs.values(), key=lambda s: s.created)[-MAX_KEPT:]
            self._subs = {s.local_id: s for s in subs}
            data = {"version": 1, "submissions": [asdict(s) for s in subs]}
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp, self.path)
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                failsoft.suppress("core.nodes.jobs:listener")

    def add_listener(self, fn: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: fn in self._listeners and self._listeners.remove(fn)

    def list(self, limit: int = 20) -> list[Submission]:
        with self._lock:
            return sorted(self._subs.values(), key=lambda s: s.created, reverse=True)[:limit]

    def get(self, local_id: str) -> Submission | None:
        with self._lock:
            return self._subs.get(local_id)

    def pending(self) -> list[Submission]:
        return [s for s in self.list(MAX_KEPT) if not s.terminal]

    # ── submit ───────────────────────────────────────────────────────────────
    def submit(self, kind: str, capability: str, payload: dict, *, deadline_s: float = 600.0,
               priority: str = "normal", privacy: str = "personal") -> Submission:
        """Place and send a job. Raises RoutingBlocked when no node may take it."""
        request = {"kind": kind, "capability": capability, "payload": dict(payload),
                   "idempotency_key": "jv-" + secrets.token_hex(12), "deadline_s": float(deadline_s),
                   "priority": priority, "privacy": privacy}
        protocol.parse_job_spec(request)                     # refuse locally what the node would refuse
        placement = router.place(capability, self.registry.nodes(), privacy=privacy)
        if placement.target != "node":
            raise RoutingBlocked(placement)
        state = self.registry.get(placement.node)
        sub = Submission(local_id="rj_" + secrets.token_hex(6), node=placement.node,
                         node_id=state.hello.node_id, idempotency_key=request["idempotency_key"],
                         kind=kind, capability=capability, request=request, deadline_s=float(deadline_s))
        with self._lock:
            self._subs[sub.local_id] = sub
        self._save()                                          # saved before it is sent
        self._send(sub)
        return sub

    def _send(self, sub: Submission) -> None:
        state = self.registry.get(sub.node)
        if state is None:
            self._update(sub, state="failed", error=f"the {sub.node} node was removed from the configuration")
            return
        try:
            view = protocol.parse_job_view(self.registry.client.call(
                state.config, "job_submit", {"request": protocol.dumps(sub.request)}))
        except NodeRefused as exc:
            self._update(sub, state="failed", error=f"The node refused the job: {exc}")
            return
        except (NodeUnavailable, ProtocolError) as exc:
            self.registry.mark_unreachable(sub.node, str(exc))
            self._update(sub, state="waiting_for_node", message=f"Waiting for {sub.node}: {exc}")
            return
        self._apply_view(sub, view)

    # ── follow ───────────────────────────────────────────────────────────────
    def refresh(self, sub: Submission) -> Submission:
        if sub.terminal:
            return sub
        if not sub.job_id:
            self._send(sub)                                   # same key: never a duplicate
            return sub
        state = self.registry.get(sub.node)
        if state is None:
            self._update(sub, state="unknown", error="the node was removed from the configuration")
            return sub
        try:
            tool = "job_status"
            data = self.registry.client.call(state.config, tool, {"job_id": sub.job_id})
            view = protocol.parse_job_view(data)
            if view.state == "succeeded":
                view = protocol.parse_job_view(
                    self.registry.client.call(state.config, "job_result", {"job_id": sub.job_id}))
        except NodeRefused as exc:
            self._update(sub, state="unknown", error=f"The node no longer knows this job: {exc}")
            return sub
        except (NodeUnavailable, ProtocolError) as exc:
            self.registry.mark_unreachable(sub.node, str(exc))
            self._update(sub, state="waiting_for_node", message=f"Waiting for {sub.node} to answer again.")
            return sub
        self._apply_view(sub, view)
        return sub

    def _apply_view(self, sub: Submission, view: protocol.JobView) -> None:
        if (sub.job_id and view.id != sub.job_id) or view.node_id != sub.node_id \
                or view.lease_epoch < sub.lease_epoch:
            failsoft.suppress("core.nodes.jobs:stale_view")   # a stale or foreign answer: ignore it
            return
        changes = dict(job_id=view.id, state=view.state, lease_epoch=view.lease_epoch,
                       attempts=view.attempts, progress=view.progress, message=view.message,
                       error=view.error)
        if view.state == "succeeded":
            if view.result is None:
                # A status (or a re-submit) said "succeeded" without the result: fetch it on the
                # next refresh before reporting success.
                changes.update(state="running", message="Fetching the result.")
            else:
                changes["result"] = view.result
        was_terminal = sub.terminal
        self._update(sub, **changes)
        if sub.terminal and not was_terminal and self._emit is not None:
            self._emit("node_job_finished", {"node": sub.node, "kind": sub.kind, "state": sub.state})

    def _update(self, sub: Submission, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(sub, key, value)
            sub.updated = self._clock()
        self._save()

    def cancel(self, sub: Submission) -> bool:
        """Ask the node to stop. True once the node confirmed (or the job never reached it)."""
        if sub.terminal:
            return True
        self._update(sub, cancel_requested=True)
        if not sub.job_id:
            # Never acknowledged: the same key may still arrive later, so keep asking on refresh.
            return False
        state = self.registry.get(sub.node)
        if state is None:
            return False
        try:
            view = protocol.parse_job_view(self.registry.client.call(state.config, "job_cancel",
                                                                     {"job_id": sub.job_id}))
        except (NodeUnavailable, NodeRefused, ProtocolError):
            return False
        self._apply_view(sub, view)
        return sub.terminal

    def follow(self, sub: Submission, *, stopped: Callable[[], bool] = lambda: False,
               poll_s: float = 1.0) -> Submission:
        """Block until the job ends, the owner stops it, or the deadline passes."""
        give_up_at = sub.created + sub.deadline_s + DEADLINE_GRACE_S
        cancel_since: float | None = None
        while not sub.terminal:
            if stopped() and cancel_since is None:
                cancel_since = self._clock()
            if cancel_since is not None:
                if self.cancel(sub):
                    break
                if not sub.job_id:
                    self.refresh(sub)                          # learn the job id, then cancel it
                if self._clock() - cancel_since > CANCEL_GIVE_UP_S:
                    self._update(sub, state="unknown",
                                 error="Stop requested, but the node did not confirm. It stops at its deadline at the latest.")
                    break
            else:
                self.refresh(sub)
            if self._clock() > give_up_at and not sub.terminal:
                self._update(sub, state="unknown",
                             error="No final answer from the node before the deadline. Nothing is reported as done.")
                break
            if not sub.terminal:
                self._sleep(poll_s if sub.state != "waiting_for_node" else min(5.0, poll_s * 5))
        return sub


def describe(sub: Submission) -> str:
    """A truthful sentence for the voice reply and the job log."""
    if sub.state == "succeeded":
        return f"The {sub.kind} job finished on {sub.node}."
    if sub.state == "cancelled":
        return f"The {sub.kind} job on {sub.node} was stopped."
    if sub.state in ("failed", "expired", "interrupted"):
        return f"The {sub.kind} job on {sub.node} {sub.state}: {sub.error or 'no reason given'}."
    if sub.state == "waiting_for_node":
        return f"The {sub.kind} job is waiting for {sub.node} to answer."
    if sub.state == "unknown":
        return f"I don't know how the {sub.kind} job on {sub.node} ended: {sub.error}"
    pct = f" ({round(sub.progress * 100)}%)" if sub.progress is not None else ""
    return f"The {sub.kind} job on {sub.node} is {sub.state}{pct}."


_JOBS: RemoteJobs | None = None
_JOBS_LOCK = threading.Lock()


def get_remote_jobs() -> RemoteJobs:
    global _JOBS
    with _JOBS_LOCK:
        if _JOBS is None:
            from jarvis.core.nodes.registry import _emit_hook, get_registry
            _JOBS = RemoteJobs(get_registry(), emit=_emit_hook)
        return _JOBS


def reset_remote_jobs_for_tests(jobs: RemoteJobs | None = None) -> None:
    global _JOBS
    with _JOBS_LOCK:
        _JOBS = jobs
