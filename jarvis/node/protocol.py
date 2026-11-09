"""Versioned, closed message shapes shared by the worker node and the laptop.

Both ends validate with these functions. Anything outside the closed sets, out of
range, or carrying unknown keys is refused with :class:`ProtocolError`, never
coerced — the node treats every request as untrusted input and the laptop treats
every node answer the same way.

Wire format: every MCP tool on the node takes and returns one JSON object as text
(``json.dumps`` of the shapes below), so the same validators run on both sides and
no SDK-specific structured-output feature is needed.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

NODE_PROTOCOL_VERSION = 1

#: Closed capability names. A node advertises a subset; a job asks for exactly one.
CAPABILITIES = frozenset({
    "assistant.orchestrate",
    "engineering.cadquery",
    "engineering.ngspice",
    "engineering.openmodelica",
    "laptop.desktop_control",
    "laptop.audio_io",
    "phone.dashboard",
})
#: Capabilities that only the laptop itself may serve; the router never sends them away.
LAPTOP_ONLY = frozenset({"laptop.desktop_control", "laptop.audio_io"})

ROLES = ("worker", "laptop", "phone")
JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled", "expired", "interrupted")
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "expired", "interrupted"})
PRIORITIES = ("low", "normal", "high")
PRIVACY_CLASSES = ("public", "personal", "sensitive")
HEALTH_STATES = ("ok", "degraded")

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_MESSAGE_CHARS = 300
MAX_DEADLINE_S = 6 * 3600.0
MIN_DEADLINE_S = 1.0

_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}(\.[a-z][a-z0-9_]{0,23}){1,2}$")
_IDEM_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_JOB_ID_RE = re.compile(r"^job_[0-9a-f]{32}$")
_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,32}$")


class ProtocolError(ValueError):
    """A message that does not match the protocol. The text is safe to show."""


# ── small checks ─────────────────────────────────────────────────────────────

def _require_keys(data: Any, allowed: set[str], required: set[str], what: str) -> dict:
    if not isinstance(data, dict):
        raise ProtocolError(f"{what} must be an object")
    unknown = set(data) - allowed
    if unknown:
        raise ProtocolError(f"{what} has unknown field(s): {', '.join(sorted(map(str, unknown)))[:120]}")
    missing = required - set(data)
    if missing:
        raise ProtocolError(f"{what} is missing: {', '.join(sorted(missing))}")
    return data


def _number(value: Any, lo: float, hi: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{what} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < lo or number > hi:
        raise ProtocolError(f"{what} must be between {lo:g} and {hi:g}")
    return number


def _choice(value: Any, options, what: str) -> str:
    if value not in options:
        raise ProtocolError(f"{what} must be one of: {', '.join(sorted(options))}")
    return str(value)


def _text(value: Any, limit: int, what: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{what} must be text")
    return value[:limit]


def json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"value is not plain JSON: {exc}") from None


def check_job_id(value: Any) -> str:
    if not isinstance(value, str) or not _JOB_ID_RE.match(value):
        raise ProtocolError("job id is malformed")
    return value


def check_node_id(value: Any) -> str:
    if not isinstance(value, str) or not _NODE_ID_RE.match(value):
        raise ProtocolError("node id must be lowercase letters, digits or '-' (max 32)")
    return value


def check_capabilities(values: Any) -> list[str]:
    if not isinstance(values, list) or len(values) > len(CAPABILITIES):
        raise ProtocolError("capabilities must be a list")
    out = []
    for value in values:
        out.append(_choice(value, CAPABILITIES, "capability"))
    return sorted(set(out))


# ── job request ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobSpec:
    kind: str
    capability: str
    idempotency_key: str
    payload: dict = field(default_factory=dict)
    deadline_s: float = 600.0
    priority: str = "normal"
    privacy: str = "personal"

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        """Stable text of the request, used to refuse an idempotency key reused for a different job."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


_SPEC_FIELDS = {"kind", "capability", "idempotency_key", "payload", "deadline_s", "priority", "privacy"}


def parse_job_spec(data: Any) -> JobSpec:
    row = _require_keys(data, _SPEC_FIELDS, {"kind", "capability", "idempotency_key"}, "job request")
    kind = row["kind"]
    if not isinstance(kind, str) or not _KIND_RE.match(kind):
        raise ProtocolError("job kind is malformed")
    capability = _choice(row["capability"], CAPABILITIES, "capability")
    if capability in LAPTOP_ONLY:
        raise ProtocolError(f"{capability} runs only on the laptop")
    key = row["idempotency_key"]
    if not isinstance(key, str) or not _IDEM_RE.match(key):
        raise ProtocolError("idempotency key must be 8-64 letters, digits, '-' or '_'")
    payload = row.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object")
    if json_size(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError("payload is too large")
    deadline = _number(row.get("deadline_s", 600.0), MIN_DEADLINE_S, MAX_DEADLINE_S, "deadline_s")
    priority = _choice(row.get("priority", "normal"), PRIORITIES, "priority")
    privacy = _choice(row.get("privacy", "personal"), PRIVACY_CLASSES, "privacy")
    if privacy == "sensitive":
        raise ProtocolError("sensitive work never leaves the laptop")
    return JobSpec(kind, capability, key, dict(payload), deadline, priority, privacy)


# ── node identity and health ─────────────────────────────────────────────────

@dataclass(frozen=True)
class NodeHello:
    protocol: int
    node_id: str
    role: str
    software: str
    capabilities: tuple[str, ...]
    job_kinds: tuple[str, ...]


def parse_hello(data: Any) -> NodeHello:
    row = _require_keys(data, {"protocol", "node_id", "role", "software", "capabilities", "job_kinds"},
                        {"protocol", "node_id", "role", "software", "capabilities", "job_kinds"}, "hello")
    protocol = row["protocol"]
    if protocol != NODE_PROTOCOL_VERSION:
        raise ProtocolError(f"node speaks protocol {protocol!r}; this JARVIS speaks {NODE_PROTOCOL_VERSION}")
    software = row["software"]
    if not isinstance(software, str) or not _VERSION_RE.match(software):
        raise ProtocolError("software version is malformed")
    kinds = row["job_kinds"]
    if not isinstance(kinds, list) or len(kinds) > 64 or not all(isinstance(k, str) and _KIND_RE.match(k) for k in kinds):
        raise ProtocolError("job kinds are malformed")
    return NodeHello(int(protocol), check_node_id(row["node_id"]), _choice(row["role"], ROLES, "role"),
                     software, tuple(check_capabilities(row["capabilities"])), tuple(sorted(set(kinds))))


@dataclass(frozen=True)
class Health:
    status: str
    cpu_percent: float
    ram_available_mb: float
    ram_total_mb: float
    disk_free_gb: float
    gpu: bool
    running_jobs: int
    queued_jobs: int
    max_parallel: int


_HEALTH_FIELDS = {"status", "cpu_percent", "ram_available_mb", "ram_total_mb", "disk_free_gb", "gpu",
                  "running_jobs", "queued_jobs", "max_parallel"}


def parse_health(data: Any) -> Health:
    row = _require_keys(data, _HEALTH_FIELDS, _HEALTH_FIELDS, "health")
    if not isinstance(row["gpu"], bool):
        raise ProtocolError("gpu must be true or false")
    return Health(
        status=_choice(row["status"], HEALTH_STATES, "status"),
        cpu_percent=_number(row["cpu_percent"], 0, 100, "cpu_percent"),
        ram_available_mb=_number(row["ram_available_mb"], 0, 16_777_216, "ram_available_mb"),
        ram_total_mb=_number(row["ram_total_mb"], 0, 16_777_216, "ram_total_mb"),
        disk_free_gb=_number(row["disk_free_gb"], 0, 1_048_576, "disk_free_gb"),
        gpu=row["gpu"],
        running_jobs=int(_number(row["running_jobs"], 0, 10_000, "running_jobs")),
        queued_jobs=int(_number(row["queued_jobs"], 0, 10_000, "queued_jobs")),
        max_parallel=int(_number(row["max_parallel"], 1, 64, "max_parallel")),
    )


# ── job status ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobView:
    id: str
    kind: str
    state: str
    node_id: str
    lease_epoch: int
    attempts: int
    created: float
    started: float | None
    finished: float | None
    progress: float | None          # only when the job itself reported it; never estimated
    message: str
    error: str
    result: dict | None             # present only in job_result answers

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


_VIEW_FIELDS = {"id", "kind", "state", "node_id", "lease_epoch", "attempts", "created", "started",
                "finished", "progress", "message", "error", "result"}


def _opt_time(value: Any, what: str) -> float | None:
    return None if value is None else _number(value, 0, 4_102_444_800, what)


def parse_job_view(data: Any) -> JobView:
    row = _require_keys(data, _VIEW_FIELDS, _VIEW_FIELDS - {"result"}, "job status")
    kind = row["kind"]
    if not isinstance(kind, str) or not _KIND_RE.match(kind):
        raise ProtocolError("job kind is malformed")
    progress = row["progress"]
    if progress is not None:
        progress = _number(progress, 0, 1, "progress")
    result = row.get("result")
    if result is not None:
        if not isinstance(result, dict):
            raise ProtocolError("result must be an object")
        if json_size(result) > MAX_RESULT_BYTES:
            raise ProtocolError("result is too large")
    return JobView(
        id=check_job_id(row["id"]), kind=kind, state=_choice(row["state"], JOB_STATES, "state"),
        node_id=check_node_id(row["node_id"]),
        lease_epoch=int(_number(row["lease_epoch"], 0, 1_000_000, "lease_epoch")),
        attempts=int(_number(row["attempts"], 0, 1_000, "attempts")),
        created=_number(row["created"], 0, 4_102_444_800, "created"),
        started=_opt_time(row["started"], "started"), finished=_opt_time(row["finished"], "finished"),
        progress=progress, message=_text(row["message"], MAX_MESSAGE_CHARS, "message"),
        error=_text(row["error"], MAX_MESSAGE_CHARS, "error"), result=result,
    )


def parse_error(data: Any) -> str | None:
    """A node answer of the form {"error": "..."} (refusal), else None."""
    if isinstance(data, dict) and set(data) == {"error"} and isinstance(data["error"], str):
        return data["error"][:MAX_MESSAGE_CHARS]
    return None


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"answer is not JSON: {exc}") from None
