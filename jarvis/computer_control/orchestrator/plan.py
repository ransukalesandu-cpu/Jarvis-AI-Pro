"""A computer-control plan: steps that each call one registered cc tool."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from jarvis.agent.dependency_graph import DependencyGraphError, topological_sort_steps

MAX_STEPS = 25
_REF = re.compile(r"\{\{\s*(\d+)\.([a-zA-Z0-9_.]+)\s*\}\}")


class PlanError(ValueError):
    pass


@dataclass
class Step:
    index: int
    tool: str                                  # a cc_* tool id
    args: dict = field(default_factory=dict)
    description: str = ""
    depends_on: list = field(default_factory=list)
    expect: dict = field(default_factory=dict)  # {"window": "...", "text": "...", "file": "..."}
    optional: bool = False                      # failure does not fail the task

    def references(self) -> list[int]:
        return sorted({int(m.group(1)) for m in _REF.finditer(json.dumps(self.args, default=str))})

    def as_dict(self) -> dict:
        return {"index": self.index, "tool": self.tool, "args": self.args,
                "description": self.description, "depends_on": list(self.depends_on),
                "expect": self.expect, "optional": self.optional}


@dataclass
class Plan:
    objective: str
    steps: list[Step]
    source: str = "heuristic"                   # heuristic | model
    notes: str = ""

    def describe(self) -> str:
        return "; ".join(f"{s.index + 1}. {s.description or s.tool}" for s in self.steps)


def resolve_refs(value: Any, outputs: dict[int, dict]) -> tuple[Any, bool]:
    """Replace ``{{N.data.path}}`` with step N's result. Returns (value, used_refs)."""
    used = False

    def lookup(index: int, path: str):
        node: Any = outputs.get(index)
        for part in path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return None
        return node

    def walk(v):
        nonlocal used
        if isinstance(v, str):
            whole = _REF.fullmatch(v.strip())
            if whole:
                used = True
                return lookup(int(whole.group(1)), whole.group(2))

            def swap(m):
                nonlocal used
                used = True
                found = lookup(int(m.group(1)), m.group(2))
                return "" if found is None else str(found)
            return _REF.sub(swap, v)
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value), used


def build(objective: str, raw_steps: Iterable[dict], known_tools: Iterable[str], *,
          source: str = "model", notes: str = "") -> Plan:
    """Validate raw step dicts (from the model or the heuristic planner)."""
    known = set(known_tools)
    steps: list[Step] = []
    raw = list(raw_steps)
    if not raw:
        raise PlanError("the plan has no steps")
    if len(raw) > MAX_STEPS:
        raise PlanError(f"the plan has {len(raw)} steps (max {MAX_STEPS})")
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError(f"step {i} is not an object")
        tool = str(item.get("tool") or "").strip()
        if tool not in known:
            raise PlanError(f"step {i} uses unknown tool {tool!r}")
        args = item.get("args") or {}
        if not isinstance(args, dict):
            raise PlanError(f"step {i} args must be an object")
        expect = item.get("expect") or {}
        if not isinstance(expect, dict):
            raise PlanError(f"step {i} expect must be an object")
        deps = item.get("depends_on")
        if deps is None:
            deps = [i - 1] if i > 0 else []
        steps.append(Step(index=i, tool=tool, args=dict(args),
                          description=str(item.get("description") or "")[:200],
                          depends_on=list(deps), expect=dict(expect),
                          optional=bool(item.get("optional", False))))
    for step in steps:
        for ref in step.references():
            if ref == step.index or not 0 <= ref < len(steps):
                raise PlanError(f"step {step.index} uses the result of step {ref}, which it cannot")
            if ref not in step.depends_on:
                step.depends_on.append(ref)
    original = {id(s): s.index for s in steps}
    try:
        ordered = topological_sort_steps(steps)
    except DependencyGraphError as exc:
        raise PlanError(str(exc)) from exc
    # references were written against the original indexes: rewrite them
    order = {original[id(s)]: i for i, s in enumerate(ordered)}
    for step in ordered:
        step.args = _reindex(step.args, order)
    return Plan(objective=objective, steps=ordered, source=source, notes=notes)


def _reindex(value: Any, order: dict[int, int]) -> Any:
    if isinstance(value, str):
        return _REF.sub(lambda m: "{{%d.%s}}" % (order.get(int(m.group(1)), int(m.group(1))), m.group(2)),
                        value)
    if isinstance(value, dict):
        return {k: _reindex(v, order) for k, v in value.items()}
    if isinstance(value, list):
        return [_reindex(v, order) for v in value]
    return value


def parse_model_json(text: str) -> Optional[dict]:
    """The first JSON object in a model answer (fenced or bare), or None."""
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    candidate = fence.group(1) if fence else raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        value = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None
