"""Laptop-side registry and remote jobs against an in-process node (no network).

FakeClient routes calls to a real NodeService and can drop answers, which is how
node loss, lost replies, reconnection and stale answers are reproduced exactly.
"""
from __future__ import annotations

import json
import time

import pytest

from jarvis.core.mcp_client import ServerConfig
from jarvis.core.nodes.client import NodeRefused, NodeUnavailable
from jarvis.core.nodes.jobs import RemoteJobs, RoutingBlocked, describe
from jarvis.core.nodes.registry import NodeRegistry
from jarvis.node.config import NodeConfig
from jarvis.node.service import NodeService


class FakeClient:
    def __init__(self, service):
        self.service = service
        self.down = False
        self.drop_reply_once: set[str] = set()      # tool names whose next reply is "lost"
        self.calls: list[str] = []
        self.tamper = None                           # fn(tool, answer) -> answer

    def call(self, cfg, tool, arguments=None, timeout=15):
        self.calls.append(tool)
        if self.down:
            raise NodeUnavailable(f"the {cfg.name} node is unreachable (ConnectError)")
        args = arguments or {}
        device = "laptop"
        s = self.service
        if tool == "node_hello":
            answer = s.hello(device)
        elif tool == "node_health":
            answer = s.health(device)
        elif tool == "job_submit":
            try:
                request = json.loads(args["request"])
            except ValueError:
                request = None
            answer = s.submit(device, request)
        elif tool == "job_status":
            answer = s.status(device, args["job_id"])
        elif tool == "job_result":
            answer = s.result(device, args["job_id"])
        elif tool == "job_cancel":
            answer = s.cancel(device, args["job_id"])
        else:
            raise AssertionError(tool)
        if tool in self.drop_reply_once:            # the node did the work, the reply was lost
            self.drop_reply_once.discard(tool)
            raise NodeUnavailable("reply lost")
        if self.tamper:
            answer = self.tamper(tool, answer)
        answer = json.loads(json.dumps(answer))
        if isinstance(answer, dict) and set(answer) == {"error"}:
            raise NodeRefused(answer["error"])
        return answer

    def forget(self, name):
        pass

    def close(self):
        pass


CFG = ServerConfig("forge", "", url="https://forge.example/mcp", bearer_env="FORGE_TOKEN", role="worker")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TOKEN", "t" * 32)
    service = NodeService(NodeConfig(state_dir=tmp_path / "node", lease_s=3, max_parallel=1))
    client = FakeClient(service)
    events: list[tuple[str, dict]] = []
    emit = lambda e, p: events.append((e, p))  # noqa: E731
    registry = NodeRegistry(client=client, config_loader=lambda: {"forge": CFG}, emit=emit)
    jobs = RemoteJobs(registry, path=tmp_path / "subs.json", emit=emit, sleep=lambda s: time.sleep(min(s, 0.05)))
    yield service, client, registry, jobs, events, tmp_path
    service.stop()


def test_registry_transitions_and_hooks(env, monkeypatch):
    _service, client, registry, _jobs, events, _ = env
    assert registry.poll("forge").status == "online"
    client.down = True
    assert registry.poll("forge").status == "offline"
    client.down = False
    assert registry.poll("forge").status == "online"
    assert [e for e, _ in events] == ["node_online", "node_offline", "node_online"]
    assert all("t" * 32 not in json.dumps(p) for _, p in events)
    monkeypatch.delenv("FORGE_TOKEN")
    state = registry.poll("forge")
    assert state.status == "unconfigured" and "FORGE_TOKEN" in state.last_error
    public = state.public()
    assert "url" not in public and "forge.example" not in json.dumps(public)


def test_incompatible_node_is_not_used(env):
    _service, client, registry, jobs, _events, _ = env
    client.tamper = lambda tool, a: {**a, "protocol": 99} if tool == "node_hello" else a
    assert registry.poll("forge").status == "incompatible"
    with pytest.raises(RoutingBlocked):
        jobs.submit("diag.echo", "assistant.orchestrate", {"text": "x"})


def test_submit_follow_success(env):
    _service, _client, registry, jobs, events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.echo", "assistant.orchestrate", {"text": "hi"})
    jobs.follow(sub, poll_s=0.05)
    assert sub.state == "succeeded" and sub.result["echo"] == "hi"
    assert describe(sub) == "The diag.echo job finished on forge."
    assert ("node_job_finished", {"node": "forge", "kind": "diag.echo", "state": "succeeded"}) in events


def test_lost_submit_reply_never_duplicates(env):
    service, client, registry, jobs, _events, _ = env
    registry.poll("forge")
    client.drop_reply_once.add("job_submit")
    sub = jobs.submit("diag.echo", "assistant.orchestrate", {"text": "once"})
    assert sub.state == "waiting_for_node" and not sub.job_id
    jobs.follow(sub, poll_s=0.05)                  # re-sends with the same idempotency key
    assert sub.state == "succeeded"
    assert len(service.ledger.list("laptop", 100)) == 1


def test_node_loss_mid_job_waits_then_resumes(env):
    service, client, registry, jobs, _events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 1})
    client.down = True
    jobs.refresh(sub)
    assert sub.state == "waiting_for_node"          # not failed, not done
    assert "waiting" in describe(sub)
    client.down = False
    jobs.follow(sub, poll_s=0.05)
    assert sub.state == "succeeded" and len(service.ledger.list("laptop", 100)) == 1


def test_stale_or_foreign_answers_are_ignored(env):
    _service, client, registry, jobs, _events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 30})
    sub.lease_epoch = 5                                  # the laptop has already seen epoch 5
    fake = {"state": "succeeded", "result": {"fake": 1}}
    client.tamper = lambda tool, a: {**a, **fake, "lease_epoch": 4} if tool in ("job_status", "job_result") else a
    jobs.refresh(sub)                                    # an older claim's answer
    assert (sub.state, sub.result) == ("queued", None) or (sub.state == "running" and sub.result is None)
    client.tamper = lambda tool, a: {**a, **fake, "lease_epoch": 9, "node_id": "impostor"} \
        if tool in ("job_status", "job_result") else a
    jobs.refresh(sub)                                    # another machine answering at this address
    assert sub.result is None and sub.state != "succeeded"
    client.tamper = None
    jobs.cancel(sub)


def test_cancel_propagates_and_is_confirmed(env):
    service, _client, registry, jobs, _events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 30})
    started = time.time()
    jobs.follow(sub, stopped=lambda: time.time() - started > 0.3, poll_s=0.05)
    assert sub.state == "cancelled"
    assert service.ledger.get(sub.job_id).state == "cancelled" or service.ledger.get(sub.job_id).cancel_requested


def test_cancel_while_node_is_down_is_reported_honestly(env, monkeypatch):
    _service, client, registry, jobs, _events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 30})
    client.down = True
    clock = {"t": time.time()}
    jobs._clock = lambda: clock["t"]
    real_sleep = jobs._sleep

    def advance(s):
        clock["t"] += 10
        real_sleep(0)
    jobs._sleep = advance
    jobs.follow(sub, stopped=lambda: True, poll_s=0.05)
    assert sub.state == "unknown" and "did not confirm" in sub.error


def test_deadline_without_answer_is_not_success(env):
    _service, client, registry, jobs, _events, _ = env
    registry.poll("forge")
    sub = jobs.submit("diag.sleep", "assistant.orchestrate", {"seconds": 30}, deadline_s=5)
    client.down = True
    clock = {"t": time.time()}
    jobs._clock = lambda: clock["t"]
    jobs._sleep = lambda s: clock.__setitem__("t", clock["t"] + 60)
    jobs.follow(sub, poll_s=0.05)
    assert sub.state == "unknown" and "Nothing is reported as done" in sub.error


def test_restart_rechecks_saved_jobs_without_resending(env):
    service, client, registry, jobs, _events, tmp = env
    registry.poll("forge")
    client.drop_reply_once.add("job_submit")
    sub = jobs.submit("diag.echo", "assistant.orchestrate", {"text": "x"})
    reopened = RemoteJobs(registry, path=tmp / "subs.json", sleep=lambda s: None)     # laptop restarted
    pending = reopened.pending()
    assert [p.idempotency_key for p in pending] == [sub.idempotency_key]
    reopened.follow(pending[0], poll_s=0.01)
    assert pending[0].state == "succeeded" and len(service.ledger.list("laptop", 100)) == 1
    saved = (tmp / "subs.json").read_text()
    assert "t" * 32 not in saved


def test_routing_blocked_for_engineering_and_offline(env):
    _service, client, registry, jobs, _events, _ = env
    with pytest.raises(RoutingBlocked, match="not available"):
        jobs.submit("diag.echo", "assistant.orchestrate", {"text": "x"})     # never polled: unknown
    registry.poll("forge")
    with pytest.raises(RoutingBlocked, match="no connected node offers"):
        jobs.submit("engineering.cad", "engineering.cadquery", {})
    assert "job_submit" not in client.calls
