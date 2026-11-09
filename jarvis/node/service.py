"""The node's request handlers, independent of the transport (tested without HTTP).

Every method takes the *authenticated* device name (from its token, never from the
request body) and plain JSON-shaped input, and returns a JSON-shaped dict. Refusals
are ``{"error": "..."}`` with a sentence safe to show the owner.
"""
from __future__ import annotations

import threading
from typing import Any

from jarvis.node import kinds as kinds_module
from jarvis.node import protocol, resources
from jarvis.node.config import NodeConfig
from jarvis.node.ledger import Ledger
from jarvis.node.protocol import ProtocolError
from jarvis.node.worker import WorkerPool

SOFTWARE_VERSION = "1.0.0"
CONTROLLER_ROLE = "controller"


class NodeService:
    def __init__(self, config: NodeConfig, *, start_workers: bool = True):
        self.config = config
        self.kinds = kinds_module.available_kinds()
        self.ledger = Ledger(config.ledger_dir, kind_policy=kinds_module.policy)
        self.pool = WorkerPool(self.ledger, self.kinds, config.work_dir, node_id=config.node_id,
                               max_parallel=config.max_parallel, lease_s=config.lease_s)
        self._stop = threading.Event()
        self._sweeper: threading.Thread | None = None
        if start_workers:
            self.start()

    def start(self) -> None:
        self.pool.start()
        self._sweeper = threading.Thread(target=self._sweep_loop, name="node-sweeper", daemon=True)
        self._sweeper.start()

    def stop(self) -> None:
        self._stop.set()
        self.pool.stop()

    def _sweep_loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.ledger.sweep()
            except Exception:
                from jarvis.core import failsoft
                failsoft.suppress("node.service:sweep")

    # ── handlers ─────────────────────────────────────────────────────────────
    def capabilities(self) -> list[str]:
        return sorted({spec.capability for spec in self.kinds.values()})

    def hello(self, _device: str) -> dict:
        return {"protocol": protocol.NODE_PROTOCOL_VERSION, "node_id": self.config.node_id,
                "role": "worker", "software": SOFTWARE_VERSION,
                "capabilities": self.capabilities(), "job_kinds": sorted(self.kinds)}

    def health(self, _device: str) -> dict:
        running, queued = self.ledger.counts()
        snap = resources.snapshot(self.config.state_dir)
        degraded = snap["disk_free_gb"] < 1.0 or (snap["ram_total_mb"] and snap["ram_available_mb"] < 256)
        return {"status": "degraded" if degraded else "ok", **snap,
                "running_jobs": running, "queued_jobs": queued, "max_parallel": self.pool.max_parallel}

    def submit(self, device: str, request: Any) -> dict:
        try:
            spec = protocol.parse_job_spec(request)
            if spec.kind not in self.kinds:
                raise ProtocolError(f"this node cannot run '{spec.kind}'")
            if self.kinds[spec.kind].capability != spec.capability:
                raise ProtocolError(f"'{spec.kind}' serves {self.kinds[spec.kind].capability}, not {spec.capability}")
            job, _created = self.ledger.submit(spec, device)
        except ProtocolError as exc:
            return {"error": str(exc)}
        return job.view(self.config.node_id)

    def status(self, device: str, job_id: Any) -> dict:
        job = self._own(device, job_id)
        return job if isinstance(job, dict) else job.view(self.config.node_id)

    def result(self, device: str, job_id: Any) -> dict:
        job = self._own(device, job_id)
        return job if isinstance(job, dict) else job.view(self.config.node_id, with_result=True)

    def cancel(self, device: str, job_id: Any) -> dict:
        try:
            job_id = protocol.check_job_id(job_id)
        except ProtocolError as exc:
            return {"error": str(exc)}
        job = self.ledger.request_cancel(job_id, device)
        if job is None:
            return {"error": "no such job"}
        return job.view(self.config.node_id)

    def list(self, device: str, limit: Any = 20) -> dict:
        try:
            limit = int(protocol._number(limit, 1, 100, "limit"))
        except ProtocolError as exc:
            return {"error": str(exc)}
        return {"jobs": [j.view(self.config.node_id) for j in self.ledger.list(device, limit)]}

    def _own(self, device: str, job_id: Any):
        try:
            job_id = protocol.check_job_id(job_id)
        except ProtocolError as exc:
            return {"error": str(exc)}
        job = self.ledger.get(job_id, device)
        return job if job is not None else {"error": "no such job"}
