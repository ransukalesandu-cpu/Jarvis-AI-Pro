"""Worker-node protocol: closed shapes, strict validation, nothing coerced."""
from __future__ import annotations

import math

import pytest

from jarvis.node import protocol as p

GOOD = {"kind": "diag.echo", "capability": "assistant.orchestrate", "idempotency_key": "abcdefgh"}


def test_job_spec_accepts_minimal_and_full():
    spec = p.parse_job_spec(GOOD)
    assert (spec.kind, spec.deadline_s, spec.priority, spec.privacy) == ("diag.echo", 600.0, "normal", "personal")
    full = p.parse_job_spec({**GOOD, "payload": {"text": "hi"}, "deadline_s": 30, "priority": "high", "privacy": "public"})
    assert full.payload == {"text": "hi"} and full.priority == "high"


@pytest.mark.parametrize("change", [
    {"extra": 1},                                     # unknown field
    {"kind": "Diag.Echo"}, {"kind": "echo"}, {"kind": "a.b.c.d"},
    {"capability": "root.shell"},
    {"capability": "laptop.desktop_control"},         # laptop-only never goes to a node
    {"idempotency_key": "short"}, {"idempotency_key": "has space here"},
    {"payload": []}, {"payload": {"x": "y" * (p.MAX_PAYLOAD_BYTES + 1)}},
    {"deadline_s": 0}, {"deadline_s": math.inf}, {"deadline_s": True}, {"deadline_s": p.MAX_DEADLINE_S + 1},
    {"priority": "urgent"},
    {"privacy": "sensitive"},                         # sensitive work never leaves the laptop
])
def test_job_spec_refuses(change):
    with pytest.raises(p.ProtocolError):
        p.parse_job_spec({**GOOD, **change})


def test_job_spec_refuses_missing_and_non_objects():
    for bad in ({}, {"kind": "diag.echo"}, None, [], "x"):
        with pytest.raises(p.ProtocolError):
            p.parse_job_spec(bad)


def test_fingerprint_changes_with_payload():
    a = p.parse_job_spec({**GOOD, "payload": {"text": "a"}})
    b = p.parse_job_spec({**GOOD, "payload": {"text": "b"}})
    assert a.fingerprint() != b.fingerprint()


HELLO = {"protocol": 1, "node_id": "forge", "role": "worker", "software": "1.0.0",
         "capabilities": ["assistant.orchestrate"], "job_kinds": ["diag.echo"]}


def test_hello_version_is_enforced():
    assert p.parse_hello(HELLO).node_id == "forge"
    with pytest.raises(p.ProtocolError, match="protocol"):
        p.parse_hello({**HELLO, "protocol": 2})
    for change in ({"node_id": "Forge!"}, {"role": "king"}, {"capabilities": ["evil"]},
                   {"job_kinds": ["../x"]}, {"software": "1 0"}):
        with pytest.raises(p.ProtocolError):
            p.parse_hello({**HELLO, **change})


HEALTH = {"status": "ok", "cpu_percent": 10, "ram_available_mb": 4000, "ram_total_mb": 8000,
          "disk_free_gb": 50, "gpu": False, "running_jobs": 0, "queued_jobs": 0, "max_parallel": 2}


def test_health_ranges():
    assert p.parse_health(HEALTH).max_parallel == 2
    for change in ({"cpu_percent": 101}, {"gpu": 1}, {"status": "great"}, {"max_parallel": 0}, {"extra": 1}):
        with pytest.raises(p.ProtocolError):
            p.parse_health({**HEALTH, **change})


VIEW = {"id": "job_" + "a" * 32, "kind": "diag.echo", "state": "running", "node_id": "forge", "lease_epoch": 1,
        "attempts": 1, "created": 1.0, "started": 2.0, "finished": None, "progress": None, "message": "", "error": ""}


def test_job_view():
    assert not p.parse_job_view(VIEW).terminal
    assert p.parse_job_view({**VIEW, "state": "succeeded", "result": {"ok": 1}}).result == {"ok": 1}
    for change in ({"id": "job_x"}, {"state": "done"}, {"progress": 1.5}, {"result": [1]}, {"lease_epoch": -1}):
        with pytest.raises(p.ProtocolError):
            p.parse_job_view({**VIEW, **change})


def test_refusal_shape():
    assert p.parse_error({"error": "no"}) == "no"
    assert p.parse_error({"error": "no", "x": 1}) is None
    assert p.parse_error(VIEW) is None
