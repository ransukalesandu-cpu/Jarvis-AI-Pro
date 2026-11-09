"""End to end: a real `python -m jarvis.node serve` process, killed and restarted mid-job.

Proves the acceptance points that only a separate process can: the laptop shows
"waiting for node" (not failure) while the node is gone, the restarted node re-runs an
idempotent job once (attempt 2, new lease epoch) instead of duplicating it, the laptop
accepts only the new epoch's result, and cancellation reaches the node.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jarvis.core.mcp_client import ServerConfig
from jarvis.core.nodes.jobs import RemoteJobs
from jarvis.core.nodes.registry import NodeRegistry
from jarvis.node.ledger import Ledger

pytestmark = pytest.mark.slow
REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(env):
    proc = subprocess.Popen([sys.executable, "-m", "jarvis.node", "serve"], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = int(env["JARVIS_NODE_PORT"])
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("node did not start")


def _stop(proc):
    proc.kill()
    proc.wait(10)


def test_node_restart_mid_job(tmp_path, monkeypatch):
    env = dict(os.environ, JARVIS_NODE_STATE=str(tmp_path / "node"), JARVIS_NODE_PORT=str(_free_port()),
               JARVIS_DATA_DIR=str(tmp_path / "data"), JARVIS_NODE_MAX_PARALLEL="1")
    out = subprocess.run([sys.executable, "-m", "jarvis.node", "token", "laptop"], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout
    token = out.splitlines()[2].strip()
    monkeypatch.setenv("E2E_NODE_TOKEN", token)
    cfg = ServerConfig("forge", "", url=f"http://127.0.0.1:{env['JARVIS_NODE_PORT']}/mcp",
                       bearer_env="E2E_NODE_TOKEN", role="worker")
    events = []
    registry = NodeRegistry(config_loader=lambda: {"forge": cfg}, emit=lambda e, p: events.append(e))
    jobs = RemoteJobs(registry, path=tmp_path / "subs.json", emit=lambda e, p: events.append(e))
    proc = _start(env)
    try:
        assert registry.poll("forge").status == "online"
        sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 3})
        deadline = time.time() + 15
        while sub.state != "running" and time.time() < deadline:
            time.sleep(0.2)
            jobs.refresh(sub)
        assert sub.state == "running" and sub.lease_epoch == 1
        _stop(proc)                                            # the node dies mid-job
        jobs.refresh(sub)
        assert sub.state == "waiting_for_node"
        assert registry.poll("forge").status == "offline"
        proc = _start(env)                                     # and comes back
        assert registry.poll("forge").status == "online"
        jobs.follow(sub, poll_s=0.3)
        assert sub.state == "succeeded" and sub.result == {"slept_s": 3}
        assert (sub.attempts, sub.lease_epoch) == (2, 2)
        cancel = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 60})
        started = time.time()
        jobs.follow(cancel, stopped=lambda: time.time() - started > 1.0, poll_s=0.3)
        assert cancel.state == "cancelled" and time.time() - started < 15
    finally:
        _stop(proc)
        registry.stop()
    rows = Ledger(tmp_path / "node" / "ledger").list(None, 100)
    assert sorted(r.state for r in rows) == ["cancelled", "succeeded"]      # no duplicate job
    assert events.count("node_online") == 2 and "node_offline" in events and "node_job_finished" in events
    for path in (tmp_path / "subs.json", tmp_path / "node" / "ledger" / "ledger.json",
                 tmp_path / "node" / "ledger" / "journal.jsonl"):
        assert token not in path.read_text()
    assert token not in json.dumps(registry.snapshot())
