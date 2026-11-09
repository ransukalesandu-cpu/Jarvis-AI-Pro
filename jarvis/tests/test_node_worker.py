"""Worker pool: real child processes with limits, cancel, timeout and lost leases."""
from __future__ import annotations

import dataclasses
import threading
import time

import pytest

from jarvis.node.kinds import KINDS, policy
from jarvis.node.ledger import Ledger
from jarvis.node.protocol import parse_job_spec
from jarvis.node.worker import WorkerPool


def submit(ledger, kind, payload, key, **extra):
    job, _ = ledger.submit(parse_job_spec({"kind": kind, "capability": "assistant.orchestrate",
                                           "idempotency_key": key, "payload": payload, **extra}), "laptop")
    return job


@pytest.fixture
def setup(tmp_path):
    ledger = Ledger(tmp_path / "ledger", kind_policy=policy)
    pool = WorkerPool(ledger, KINDS, tmp_path / "work", node_id="forge", lease_s=3)
    return ledger, pool, tmp_path


def run_one(ledger, pool, holder="forge:t:w0"):
    job = ledger.claim(holder, pool.lease_s)
    return pool.run_job(job, holder)


def test_echo_succeeds_and_cleans_up(setup):
    ledger, pool, tmp = setup
    job = submit(ledger, "diag.echo", {"text": "hello"}, "k-echo0001")
    assert run_one(ledger, pool) == "succeeded"
    assert ledger.get(job.id).result["echo"] == "hello"
    assert not (tmp / "work" / job.id).exists()


def test_bad_input_and_failure_are_reported(setup):
    ledger, pool, _ = setup
    bad = submit(ledger, "diag.echo", {"text": "x", "rm": "-rf"}, "k-bad00001")
    assert run_one(ledger, pool) == "failed"
    assert "Invalid job input" in ledger.get(bad.id).error
    fail = submit(ledger, "diag.sleep", {"seconds": 0.1, "fail": True}, "k-fail0001")
    assert run_one(ledger, pool) == "failed"
    assert "asked to fail" in ledger.get(fail.id).error


def test_progress_is_real_and_cancel_kills(setup):
    ledger, pool, _ = setup
    job = submit(ledger, "diag.sleep", {"seconds": 30}, "k-slow0001")
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("state", run_one(ledger, pool)))
    t.start()
    deadline = time.time() + 10
    while ledger.get(job.id).progress is None and time.time() < deadline:
        time.sleep(0.05)
    assert 0 < ledger.get(job.id).progress < 1
    started = time.time()
    ledger.request_cancel(job.id, "laptop")
    t.join(10)
    assert out["state"] == "cancelled" and ledger.get(job.id).state == "cancelled"
    assert time.time() - started < pool.lease_s + 2          # stopped at the next renew, not at the end


def test_timeout_kills(setup):
    ledger, pool, _ = setup
    pool.kinds["diag.sleep"] = dataclasses.replace(KINDS["diag.sleep"], timeout_s=1)
    job = submit(ledger, "diag.sleep", {"seconds": 20}, "k-tout0001")
    started = time.time()
    assert run_one(ledger, pool) == "failed"
    assert "timeout" in ledger.get(job.id).error and time.time() - started < 8


def test_output_cap(setup):
    ledger, pool, _ = setup
    pool.kinds["diag.echo"] = dataclasses.replace(KINDS["diag.echo"], max_output_bytes=100)
    job = submit(ledger, "diag.echo", {"text": "y" * 1500}, "k-big00001")
    assert run_one(ledger, pool) == "failed"
    assert "output size" in ledger.get(job.id).error


def test_lost_lease_is_not_completed(setup):
    ledger, pool, _ = setup
    job = submit(ledger, "diag.sleep", {"seconds": 30}, "k-lost0001")
    claimed = ledger.claim("forge:t:w0", pool.lease_s)
    stale = dataclasses.replace(claimed)            # what this worker believes it holds
    claimed.lease_epoch += 1                       # meanwhile the ledger gave the job to another claim
    claimed.lease_holder = "forge:other:w1"
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("state", pool.run_job(stale, "forge:t:w0")))
    t.start()
    t.join(15)
    assert out["state"] == "lost"
    row = ledger.get(job.id)                        # untouched: still owned by the newer claim
    assert (row.state, row.lease_holder, row.result) == ("running", "forge:other:w1", None)


def test_pool_threads_run_queued_jobs(setup):
    ledger, pool, _ = setup
    pool.start()
    try:
        jobs = [submit(ledger, "diag.echo", {"text": str(i)}, f"k-pool000{i}") for i in range(3)]
        deadline = time.time() + 20
        while time.time() < deadline and not all(ledger.get(j.id).terminal for j in jobs):
            time.sleep(0.1)
        assert [ledger.get(j.id).state for j in jobs] == ["succeeded"] * 3
    finally:
        pool.stop()
