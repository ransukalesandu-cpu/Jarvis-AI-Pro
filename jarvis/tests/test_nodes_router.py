"""Resource-aware placement (core/nodes/router.py): pure decisions, each with its reason."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis.core.nodes.router import place
from jarvis.node.protocol import Health, NodeHello


def node(name="forge", status="online", caps=("assistant.orchestrate", "engineering.cadquery"),
         free=4000.0, running=0, queued=0, parallel=2):
    hello = NodeHello(1, name, "worker", "1.0.0", tuple(caps), ("diag.echo",))
    health = Health("ok", 10, free, 8000, 50, False, running, queued, parallel)
    usable = status in ("online", "degraded")
    return SimpleNamespace(name=name, status=status, hello=hello if usable else None,
                           health=health if usable else None, usable=usable)


def test_laptop_only_and_sensitive_stay_home():
    assert place("laptop.desktop_control", [node()]).target == "laptop"
    assert place("laptop.audio_io", [node()]).target == "laptop"
    assert place("assistant.orchestrate", [node()], privacy="sensitive").target == "blocked"
    assert place("assistant.orchestrate", [node()], privacy="sensitive", local_capable=True).target == "laptop"


def test_engineering_goes_to_the_node_and_never_falls_back():
    assert place("engineering.cadquery", [node()]).node == "forge"
    blocked = place("engineering.cadquery", [node(status="offline")], local_capable=True, laptop_free_mb=3000)
    assert blocked.target == "blocked" and "never runs on the laptop" in blocked.reason
    assert "offline" in blocked.reason


def test_best_node_by_status_then_memory_then_queue():
    a, b, c = node("a", free=2000), node("b", free=6000), node("c", status="degraded", free=9000)
    assert place("assistant.orchestrate", [a, b, c]).node == "b"
    assert place("assistant.orchestrate", [node("x", free=4000, running=2), node("y", free=4000)]).node == "y"


def test_full_or_low_memory_nodes_are_skipped():
    busy = node(running=2, queued=6, parallel=2)
    low = node("low", free=100)
    out = place("assistant.orchestrate", [busy, low])
    assert out.target == "blocked" and "busy or low on memory" in out.reason


def test_missing_capability_and_no_node():
    out = place("engineering.ngspice", [node(caps=("assistant.orchestrate",))])
    assert out.target == "blocked" and "no connected node offers" in out.reason
    assert place("assistant.orchestrate", []).reason == "no dedicated node is configured"
    assert place("root.shell", [node()]).target == "blocked"


def test_laptop_fallback_needs_the_owner_and_room():
    out = place("assistant.orchestrate", [node(status="offline")], local_capable=True, laptop_free_mb=2048)
    assert out.target == "laptop" and out.needs_owner_ok
    low = place("assistant.orchestrate", [node(status="offline")], local_capable=True, laptop_free_mb=300)
    assert low.target == "blocked" and "low on memory" in low.reason
    assert place("assistant.orchestrate", [node(status="offline")]).target == "blocked"
