"""The job kinds a node can run: a closed registry, never a name taken from a request.

Each kind declares the capability it serves, whether it is safe to run twice
(``idempotent``), how many attempts it may take, and its limits. The code that
does the work lives in :mod:`jarvis.node.jobrunner` and runs in a child process.

Phase 1 ships only diagnostic kinds (used by tests and by "test the node"). The
engineering kinds arrive with the Engineering Lab (Phase 3) and are advertised
only when their engine is installed on the node.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class KindSpec:
    name: str
    capability: str
    idempotent: bool
    max_attempts: int
    timeout_s: float
    mem_limit_mb: int
    max_output_bytes: int = 256 * 1024
    available: Callable[[], bool] = lambda: True
    description: str = ""


KINDS: dict[str, KindSpec] = {
    "diag.echo": KindSpec(
        "diag.echo", "assistant.orchestrate", idempotent=True, max_attempts=2,
        timeout_s=30, mem_limit_mb=256, description="Echo a short text (connectivity test)."),
    "diag.sleep": KindSpec(
        "diag.sleep", "assistant.orchestrate", idempotent=True, max_attempts=2,
        timeout_s=900, mem_limit_mb=256, description="Wait N seconds reporting progress (cancel/offline test)."),
}


def available_kinds() -> dict[str, KindSpec]:
    out = {}
    for name, spec in KINDS.items():
        try:
            ok = bool(spec.available())
        except Exception:
            ok = False
        if ok:
            out[name] = spec
    return out


def policy(kind: str) -> tuple[bool, int]:
    spec = KINDS.get(kind)
    if spec is None:
        return False, 1
    return spec.idempotent, spec.max_attempts
