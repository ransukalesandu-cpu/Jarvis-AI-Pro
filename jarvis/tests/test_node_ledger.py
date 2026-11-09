"""Worker-node job ledger: idempotency, leases, stale results, restart recovery, deadlines."""
from __future__ import annotations

import json

import pytest

from jarvis.node.ledger import Ledger
from jarvis.node.protocol import ProtocolError, parse_job_spec


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def spec(key="abcdefgh", kind="diag.echo", **extra):
    return parse_job_spec({"kind": kind, "capability": "assistant.orchestrate", "idempotency_key": key, **extra})


def policy(kind):
    return (kind != "diag.once", 2)            # diag.once stands in for a non-idempotent kind


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ledger(tmp_path, clock):
    return Ledger(tmp_path, kind_policy=policy, clock=clock)


def test_idempotent_submit_and_key_reuse(ledger):
    a, created = ledger.submit(spec(payload={"text": "x"}), "laptop")
    b, again = ledger.submit(spec(payload={"text": "x"}), "laptop")
    assert created and not again and a.id == b.id
    with pytest.raises(ProtocolError, match="different job"):
        ledger.submit(spec(payload={"text": "y"}), "laptop")
    other, created_other = ledger.submit(spec(payload={"text": "x"}), "phone")   # keys are per device
    assert created_other and other.id != a.id


def test_scoping_by_device(ledger):
    job, _ = ledger.submit(spec(), "laptop")
    assert ledger.get(job.id, "phone") is None
    assert ledger.request_cancel(job.id, "phone") is None
    assert ledger.list("phone") == []
    assert ledger.get(job.id, "laptop") is job


def test_claim_order_priority_then_age(ledger, clock):
    low, _ = ledger.submit(spec("k-low0001", priority="low"), "laptop")
    clock.t += 1
    normal, _ = ledger.submit(spec("k-norm0001"), "laptop")
    clock.t += 1
    high, _ = ledger.submit(spec("k-high0001", priority="high"), "laptop")
    assert [ledger.claim("w", 10).id for _ in range(3)] == [high.id, normal.id, low.id]
    assert ledger.claim("w", 10) is None


def test_stale_claim_cannot_complete(ledger, clock):
    job, _ = ledger.submit(spec(), "laptop")
    first = ledger.claim("w1", 5)
    epoch1 = first.lease_epoch
    clock.t += 6                                  # lease expires; idempotent -> re-queued
    ledger.sweep()
    assert ledger.get(job.id).state == "queued"
    second = ledger.claim("w2", 5)
    assert second.lease_epoch == epoch1 + 1
    assert not ledger.complete(job.id, "w1", epoch1, state="succeeded", result={"late": True})
    assert ledger.renew(job.id, "w1", epoch1, 5) == "lost"
    assert ledger.complete(job.id, "w2", second.lease_epoch, state="succeeded", result={"ok": True})
    assert ledger.get(job.id).result == {"ok": True}
    journal = (ledger.journal_path).read_text().splitlines()
    assert any(json.loads(line)["event"] == "stale_result_rejected" for line in journal)


def test_non_idempotent_job_is_never_rerun_after_lost_lease(ledger, clock):
    job, _ = ledger.submit(spec(kind="diag.once"), "laptop")
    ledger.claim("w", 5)
    clock.t += 6
    ledger.sweep()
    assert ledger.get(job.id).state == "interrupted"
    assert "Not re-run" in ledger.get(job.id).error


def test_attempt_budget(ledger, clock):
    job, _ = ledger.submit(spec(), "laptop")
    for _ in range(2):
        ledger.claim("w", 5)
        clock.t += 6
        ledger.sweep()
    assert ledger.get(job.id).state == "interrupted" and ledger.get(job.id).attempts == 2


def test_restart_recovery(tmp_path, clock):
    first = Ledger(tmp_path, kind_policy=policy, clock=clock)
    idem, _ = first.submit(spec("k-idem0001"), "laptop")
    once, _ = first.submit(spec("k-once0001", kind="diag.once"), "laptop")
    done, _ = first.submit(spec("k-done0001"), "laptop")
    claimed = {first.claim("w", 60).id for _ in range(3)}
    assert claimed == {idem.id, once.id, done.id}
    first.complete(done.id, "w", 1, state="succeeded", result={"x": 1})
    reopened = Ledger(tmp_path, kind_policy=policy, clock=clock)        # the node restarted
    assert reopened.get(idem.id).state == "queued"
    assert reopened.get(once.id).state == "interrupted"
    assert reopened.get(done.id).state == "succeeded" and reopened.get(done.id).result == {"x": 1}
    again, created = reopened.submit(spec("k-done0001"), "laptop")      # resubmit after restart
    assert not created and again.id == done.id


def test_deadline_and_cancel(ledger, clock):
    queued, _ = ledger.submit(spec("k-que00001", deadline_s=10), "laptop")
    assert ledger.request_cancel(queued.id, "laptop").state == "cancelled"
    running, _ = ledger.submit(spec("k-run00001"), "laptop")
    claim = ledger.claim("w", 60)
    ledger.request_cancel(running.id, "laptop")
    assert ledger.renew(running.id, "w", claim.lease_epoch, 60) == "cancel"
    ledger.complete(running.id, "w", claim.lease_epoch, state="succeeded", result={"x": 1})
    assert ledger.get(running.id).state == "cancelled"                 # never reported as success
    assert ledger.get(running.id).result is None
    late, _ = ledger.submit(spec("k-late0001", deadline_s=5), "laptop")
    clock.t += 6
    ledger.sweep()
    assert ledger.get(late.id).state == "expired"


def test_oversize_result_fails(ledger):
    job, _ = ledger.submit(spec(), "laptop")
    c = ledger.claim("w", 60)
    ledger.complete(job.id, "w", c.lease_epoch, state="succeeded", result={"x": "y" * 70_000})
    assert ledger.get(job.id).state == "failed" and ledger.get(job.id).result is None


def test_damaged_snapshot_is_kept_not_overwritten(tmp_path, clock):
    (tmp_path / "ledger.json").write_text("{not json")
    Ledger(tmp_path, kind_policy=policy, clock=clock)
    assert any(p.name.startswith("ledger.damaged-") for p in tmp_path.iterdir())


def test_secrets_are_redacted_in_errors(ledger):
    job, _ = ledger.submit(spec(), "laptop")
    c = ledger.claim("w", 60)
    ledger.complete(job.id, "w", c.lease_epoch, state="failed", error="boom token=supersecretvalue123")
    assert "supersecretvalue123" not in ledger.get(job.id).error
    assert "supersecretvalue123" not in ledger.snapshot_path.read_text()
