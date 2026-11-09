"""Bounded worker pool: claim a job, run it in a limited child process, record the outcome.

Every job runs in its own child process (``python -I jobrunner.py``) inside its own
work folder with a scrubbed environment, under the same watchdog JARVIS already
uses for code_helper (``core/sandbox.py``: wall-clock and memory limits, process-tree
kill) plus an output-size cap. The worker renews the job's lease while the child
runs; when the ledger answers ``cancel``, ``expire`` or ``lost`` the child is killed
at once. A ``lost`` lease is never completed — some other claim owns the job.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from jarvis.core import failsoft, sandbox
from jarvis.node import protocol
from jarvis.node.kinds import KindSpec
from jarvis.node.ledger import JobRecord, Ledger

RUNNER = Path(__file__).resolve().parent / "jobrunner.py"
POLL_S = 0.1


class WorkerPool:
    def __init__(self, ledger: Ledger, kinds: dict[str, KindSpec], work_dir: Path, *,
                 node_id: str, max_parallel: int = 1, lease_s: float = 15.0,
                 python: str | None = None):
        self.ledger = ledger
        self.kinds = dict(kinds)
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.node_id = node_id
        self.max_parallel = max(1, min(int(max_parallel), 16))
        self.lease_s = max(3.0, float(lease_s))
        self.python = python or sys.executable
        self.boot_id = uuid.uuid4().hex[:8]
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._procs: dict[str, subprocess.Popen] = {}
        self._procs_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        for i in range(self.max_parallel):
            t = threading.Thread(target=self._loop, args=(f"{self.node_id}:{self.boot_id}:w{i}",),
                                 name=f"node-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._procs_lock:
            procs = list(self._procs.values())
        for proc in procs:
            sandbox._kill_process_tree(proc)
        for t in self._threads:
            t.join(timeout)

    def _loop(self, holder: str) -> None:
        while not self._stop.is_set():
            try:
                job = self.ledger.claim(holder, self.lease_s, set(self.kinds))
            except Exception:
                failsoft.suppress("node.worker:claim")
                job = None
            if job is None:
                self.ledger.wait_for_change(1.0)
                continue
            try:
                self.run_job(job, holder)
            except Exception as exc:          # never leave a claimed job hanging
                failsoft.suppress("node.worker:run_job")
                self.ledger.complete(job.id, holder, job.lease_epoch, state="failed",
                                     error=f"Worker error: {type(exc).__name__}")

    # ── one job ──────────────────────────────────────────────────────────────
    def run_job(self, job: JobRecord, holder: str) -> str:
        """Run one claimed job to completion; returns the final state recorded (or 'lost')."""
        spec = self.kinds[job.kind]
        epoch = job.lease_epoch
        workspace = self.work_dir / job.id
        workspace.mkdir(parents=True, exist_ok=True)
        budget = max(1.0, min(spec.timeout_s, job.deadline_at - time.time()))
        proc = subprocess.Popen(
            [self.python, "-I", str(RUNNER)], cwd=str(workspace), env=sandbox._scrubbed_env(workspace),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self._procs_lock:
            self._procs[job.id] = proc
        flag: dict = {}
        lines: queue.Queue = queue.Queue()
        stderr_tail: list[bytes] = []
        hard_deadline = time.monotonic() + budget
        threading.Thread(target=sandbox._watchdog, args=(proc, hard_deadline, spec.mem_limit_mb, flag),
                         daemon=True).start()
        reader = threading.Thread(target=self._read_lines, args=(proc, lines, spec.max_output_bytes, flag),
                                  daemon=True)
        reader.start()
        threading.Thread(target=sandbox._drain, args=(proc.stderr, stderr_tail, 8192, proc, flag),
                         daemon=True).start()
        try:
            proc.stdin.write(json.dumps({"kind": job.kind, "payload": job.payload}).encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        result, error, outcome = None, "", None
        next_renew = time.monotonic() + self.lease_s / 3
        def drain() -> tuple[float | None, str | None]:
            nonlocal result, error
            progress = message = None
            while True:
                try:
                    item = lines.get_nowait()
                except queue.Empty:
                    return progress, message
                if "result" in item and isinstance(item["result"], dict):
                    result = item["result"]
                elif "error" in item:
                    error = str(item["error"])[:protocol.MAX_MESSAGE_CHARS]
                elif "progress" in item:
                    try:
                        progress = float(item["progress"])
                    except (TypeError, ValueError):
                        continue
                    message = str(item.get("message", ""))[:protocol.MAX_MESSAGE_CHARS]

        try:
            while True:
                progress, message = drain()
                now = time.monotonic()
                if now > hard_deadline + 2 and proc.poll() is None:
                    # Own backstop: the sandbox watchdog needs psutil and may not be running.
                    flag.setdefault("reason", "wall-clock timeout")
                    sandbox._kill_process_tree(proc)
                if progress is not None or now >= next_renew or self._stop.is_set():
                    answer = self.ledger.renew(job.id, holder, epoch, self.lease_s,
                                               progress=progress, message=message)
                    next_renew = now + self.lease_s / 3
                    if self._stop.is_set():
                        answer = "lost"          # shutting down: the next start recovers it
                    if answer in ("cancel", "expire", "lost"):
                        sandbox._kill_process_tree(proc)
                        outcome = {"cancel": "cancelled", "expire": "expired", "lost": "lost"}[answer]
                        proc.wait(10)
                        break
                if proc.poll() is not None:
                    reader.join(5)               # the reader hands over the last lines at EOF
                    drain()
                    break
                time.sleep(POLL_S)
        finally:
            with self._procs_lock:
                self._procs.pop(job.id, None)
            if proc.poll() is None:
                sandbox._kill_process_tree(proc)
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                pass
            reader.join(2)
            for stream in (proc.stdout, proc.stderr):     # a long-running node must not leak handles
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            shutil.rmtree(workspace, ignore_errors=True)   # Phase 1 kinds keep no artifacts
        if outcome == "lost":
            return "lost"
        if outcome == "cancelled":
            final, error = "cancelled", ""
        elif outcome == "expired":
            final, error = "expired", "The job did not finish before its deadline."
        elif flag.get("reason"):
            final, error, result = "failed", f"Stopped by the node: {flag['reason']}.", None
        elif proc.returncode == 0 and result is not None:
            final = "succeeded"
        else:
            final = "failed"
            if not error:
                tail = b"".join(stderr_tail).decode("utf-8", "replace").strip().splitlines()[-1:]
                error = f"The job exited with code {proc.returncode}" + (f": {tail[0][:200]}" if tail else ".")
        recorded = self.ledger.complete(job.id, holder, epoch, state=final, result=result, error=error)
        return final if recorded else "lost"

    @staticmethod
    def _read_lines(proc: subprocess.Popen, out: queue.Queue, limit: int, flag: dict) -> None:
        total = 0
        try:
            for raw in proc.stdout:
                total += len(raw)
                if total > limit:
                    flag.setdefault("reason", "output size limit exceeded")
                    sandbox._kill_process_tree(proc)
                    return
                try:
                    item = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(item, dict):
                    out.put(item)
        except (OSError, ValueError):
            return

    def running_count(self) -> int:
        with self._procs_lock:
            return len(self._procs)
