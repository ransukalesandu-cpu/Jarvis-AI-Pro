"""Validated dependency-graph helpers for agent plans.

The planner accepts dependencies as zero-based indexes into the original model
step list. This module validates the directed acyclic graph and returns a stable
topological ordering while remapping dependency indexes to the new positions.
It has no runtime, database, or optional-package dependencies.
"""

from __future__ import annotations

from collections import deque
from typing import TypeVar

T = TypeVar("T")


class DependencyGraphError(ValueError):
    """A task plan contains an invalid dependency graph."""


def topological_sort_steps(steps: list[T]) -> list[T]:
    """Return a stable topological ordering and rewrite each step's dependencies.

    Independent steps retain their original relative order. Invalid references,
    self-dependencies, and cycles fail closed instead of creating a plan that
    can stall forever in the runner.
    """
    count = len(steps)
    dependencies: list[list[int]] = []
    dependents: list[list[int]] = [[] for _ in steps]

    for index, step in enumerate(steps):
        raw = getattr(step, "depends_on", None)
        if raw is None:
            raw = []
        if not isinstance(raw, (list, tuple)):
            raise DependencyGraphError(f"step {index} dependencies must be a list")
        normalized: list[int] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, int):
                raise DependencyGraphError(f"step {index} has a non-integer dependency")
            dependency = value
            if not 0 <= dependency < count:
                raise DependencyGraphError(
                    f"step {index} references missing dependency {dependency}"
                )
            if dependency == index:
                raise DependencyGraphError(f"step {index} depends on itself")
            if dependency not in normalized:
                normalized.append(dependency)
                dependents[dependency].append(index)
        dependencies.append(normalized)

    indegree = [len(items) for items in dependencies]
    ready = deque(index for index, degree in enumerate(indegree) if degree == 0)
    order: list[int] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for child in dependents[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(order) != count:
        cyclic = [str(index) for index, degree in enumerate(indegree) if degree > 0]
        raise DependencyGraphError(
            "dependency cycle detected among step indexes " + ", ".join(cyclic)
        )

    remap = {old: new for new, old in enumerate(order)}
    ordered = [steps[index] for index in order]
    for new_index, old_index in enumerate(order):
        step = ordered[new_index]
        step.depends_on = sorted(remap[item] for item in dependencies[old_index])
        if hasattr(step, "index"):
            step.index = new_index
    return ordered
