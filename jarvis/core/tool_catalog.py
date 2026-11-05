"""A compact, read-only catalog of the tools JARVIS can run on THIS machine.

The action and plugin registries already know every tool's name, description,
schema and risk. This module only gathers them into one flat list that a planner
can read cheaply. It does not run anything, change any registry, or touch the
Gemini Live declarations.

Local tools only (owner decision, Nov 2026): tools that live on another device
(``RemoteToolRegistry``) or on the hub (``HubToolRegistry``) are left out, and so
is anything that is currently unavailable or disabled — the registries already
filter those through ``get_tool_declarations()``.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

MAX_DESCRIPTION_CHARS = 150          # same cap as main._describe_tools

# Registry classes whose tools do not run on this machine.
_NON_LOCAL_REGISTRIES = frozenset({"RemoteToolRegistry", "HubToolRegistry"})

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    description: str                         # one line, <= MAX_DESCRIPTION_CHARS
    parameters: dict = field(default_factory=dict)   # declared schema, untouched
    risk: str = ""                           # "read" | "write" | "destructive" | "" (undeclared)
    long_running: bool = False
    source: str = "action"                   # "inline" | "action" | "plugin"

    def line(self) -> str:
        return f"- {self.name}: {self.description}" if self.description else f"- {self.name}"


def one_line(text: object, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Collapse whitespace and cap the length (an ellipsis marks a cut)."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: max(limit - 1, 0)].rstrip() + "…"


def _flatten_local(registry) -> Iterable:
    """Yield the registries behind ``registry`` that run on this machine."""
    if registry is None:
        return
    if type(registry).__name__ in _NON_LOCAL_REGISTRIES:
        return
    members = getattr(registry, "registries", None)      # CompositeRegistry
    if isinstance(members, (list, tuple)):
        for member in members:
            yield from _flatten_local(member)
        return
    yield registry


def _decl_field(decl, key: str, default=None):
    if isinstance(decl, dict):
        return decl.get(key, default)
    return getattr(decl, key, default)


class ToolCatalog:
    """Immutable-ish name -> CatalogEntry map, in a stable (sorted) order."""

    def __init__(self, entries: Iterable[CatalogEntry] = ()):
        self._entries: dict[str, CatalogEntry] = {}
        for entry in entries:
            self._entries.setdefault(entry.name, entry)     # first one wins
        self._order = sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def names(self) -> list[str]:
        return list(self._order)

    def get(self, name: str) -> Optional[CatalogEntry]:
        return self._entries.get(name)

    def entries(self) -> list[CatalogEntry]:
        return [self._entries[n] for n in self._order]

    def lines(self, names: Iterable[str] | None = None) -> str:
        """One ``- name: description`` line per tool, for a planner prompt."""
        wanted = self._order if names is None else [n for n in names if n in self._entries]
        return "\n".join(self._entries[n].line() for n in wanted)


def build_catalog(*, inline: Iterable = (), registries: Iterable = ()) -> ToolCatalog:
    """Gather the local tools.

    ``inline``     — declarations that live in main.py (``TOOL_DECLARATIONS``).
    ``registries`` — ActionRegistry / PluginRegistry (or a CompositeRegistry of them);
                     anything that is not local is skipped.

    Never raises: a registry that misbehaves is skipped, a malformed declaration
    is dropped.
    """
    found: list[CatalogEntry] = []

    for decl in inline or ():
        entry = _entry_from(decl, source="inline", meta=None)
        if entry is not None:
            found.append(entry)

    for top in registries or ():
        for reg in _flatten_local(top):
            source = "plugin" if type(reg).__name__ == "PluginRegistry" else "action"
            try:
                decls = list(reg.get_tool_declarations())
            except Exception:
                continue
            for decl in decls:
                name = _decl_field(decl, "name", "")
                try:
                    meta = reg.meta(name) if hasattr(reg, "meta") else None
                except Exception:
                    meta = None
                entry = _entry_from(decl, source=source, meta=meta)
                if entry is not None:
                    found.append(entry)

    return ToolCatalog(found)


def _entry_from(decl, *, source: str, meta) -> Optional[CatalogEntry]:
    name = _decl_field(decl, "name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    params = _decl_field(decl, "parameters", None)
    return CatalogEntry(
        name=name,
        description=one_line(_decl_field(decl, "description", "")),
        parameters=copy.deepcopy(params) if isinstance(params, dict) else {},
        risk=str(getattr(meta, "risk", "") or ""),
        long_running=bool(getattr(meta, "long_running", False)),
        source=source,
    )
