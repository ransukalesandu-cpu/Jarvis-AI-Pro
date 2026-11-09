"""Where a job runs: a pure decision, explained in a sentence.

Order of checks (owner decisions, Phase 0 audit §8):

1. ``laptop.*`` capabilities stay on the laptop; ``sensitive`` work never leaves it.
2. Otherwise a healthy node that advertises the capability and has headroom
   (queue not full, enough free memory), preferring ``online`` over ``degraded``,
   then the most free memory, then the shortest queue.
3. No such node:
   * engineering work is **blocked** — engines never run on the laptop;
   * other work may run on the laptop **only if the owner agrees each time**
     (``needs_owner_ok``) and the laptop has room; otherwise it is blocked with
     the real reason (node offline / busy / missing capability).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from jarvis.node.protocol import CAPABILITIES, LAPTOP_ONLY

MIN_NODE_FREE_MB = 256
QUEUE_FACTOR = 4                      # at most max_parallel * 4 jobs waiting on a node
LAPTOP_MIN_FREE_MB = 1024             # the laptop has 4 GB; never squeeze the voice loop


@dataclass(frozen=True)
class Placement:
    target: str                       # "node" | "laptop" | "blocked"
    node: str = ""
    reason: str = ""
    needs_owner_ok: bool = False


def _has_room(state) -> bool:
    h = state.health
    if h is None:
        return False
    return (h.running_jobs + h.queued_jobs) < h.max_parallel * QUEUE_FACTOR and h.ram_available_mb >= MIN_NODE_FREE_MB


def place(capability: str, nodes: Iterable, *, privacy: str = "personal",
          local_capable: bool = False, laptop_free_mb: Optional[float] = None) -> Placement:
    if capability not in CAPABILITIES:
        return Placement("blocked", reason=f"unknown capability {capability}")
    if capability in LAPTOP_ONLY:
        return Placement("laptop", reason="this only runs on the laptop")
    if privacy == "sensitive":
        if local_capable:
            return Placement("laptop", reason="sensitive work stays on the laptop")
        return Placement("blocked", reason="sensitive work never leaves the laptop, and the laptop cannot run it")

    nodes = list(nodes)
    capable = [n for n in nodes if n.usable and capability in n.hello.capabilities]
    roomy = [n for n in capable if _has_room(n)]
    if roomy:
        best = min(roomy, key=lambda n: (n.status != "online", -n.health.ram_available_mb,
                                         n.health.running_jobs + n.health.queued_jobs, n.name))
        return Placement("node", node=best.name, reason=f"{best.name} has {capability} and room")

    if capable:
        why = f"every node with {capability} is busy or low on memory"
    elif any(n.usable for n in nodes):
        why = f"no connected node offers {capability}"
    elif nodes:
        down = ", ".join(f"{n.name} ({n.status})" for n in nodes)
        why = f"the dedicated node is not available: {down}"
    else:
        why = "no dedicated node is configured"

    if capability.startswith("engineering."):
        return Placement("blocked", reason=f"{why}; engineering work never runs on the laptop")
    if local_capable and (laptop_free_mb is None or laptop_free_mb >= LAPTOP_MIN_FREE_MB):
        return Placement("laptop", reason=f"{why}; it can run on the laptop if you agree", needs_owner_ok=True)
    if local_capable:
        return Placement("blocked", reason=f"{why}, and the laptop is low on memory")
    return Placement("blocked", reason=why)


def laptop_free_mb() -> Optional[float]:
    try:
        import psutil
        return psutil.virtual_memory().available / 1e6
    except Exception:
        return None
