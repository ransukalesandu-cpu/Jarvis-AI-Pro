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
from typing import Callable, Iterable, Optional

MAX_DESCRIPTION_CHARS = 150          # same cap as main._describe_tools

# Registry classes whose tools do not run on this machine.
_NON_LOCAL_REGISTRIES = frozenset({"RemoteToolRegistry", "HubToolRegistry"})

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "that", "this", "then", "than",
    "please", "can", "you", "your", "what", "when", "where", "how", "all", "any",
    "are", "was", "will", "has", "have", "not", "but", "out", "use", "using",
})
_STEM = 5            # compare words by their first 5 letters ("searching" ~ "search")

# Tools a plan must never call: starting a task from inside a task would recurse, and
# node jobs are placed by core/nodes, not by a plan step (Phase 2 wires tasks to nodes).
PLANNER_EXCLUDED = frozenset({"autonomous_task", "node_test"})


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

    def signature(self) -> str:
        """``name(arg, other*)`` — required arguments are starred."""
        props = self.parameters.get("properties") if isinstance(self.parameters, dict) else None
        required = set(self.parameters.get("required") or []) if isinstance(self.parameters, dict) else set()
        names = [f"{k}*" if k in required else str(k) for k in (props or {}) if k != "device"]
        return f"{self.name}({', '.join(names)})"


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

    def search(self, text: str, k: int = 20, *,
               exclude: Iterable[str] = PLANNER_EXCLUDED,
               skip_long_running: bool = True) -> list[CatalogEntry]:
        """The ``k`` tools whose name/description best match ``text``.

        Plain keyword scoring (name hit = 3, description hit = 1, words compared
        by their first five letters), deterministic, no model and no network.
        If fewer than ``k`` tools match, the list is padded in name order so a
        request in another language still gets a usable catalog.
        """
        banned = set(exclude or ())
        pool = [e for e in self.entries()
                if e.name not in banned and not (skip_long_running and e.long_running)]
        limit = max(0, int(k))
        if limit == 0 or not pool:
            return []
        wanted = {w[:_STEM] for w in _WORD_RE.findall(str(text or "").lower())
                  if w not in _STOPWORDS}

        def score(entry: CatalogEntry) -> int:
            name_words = {w[:_STEM] for w in _WORD_RE.findall(entry.name.lower().replace("_", " "))}
            desc_words = {w[:_STEM] for w in _WORD_RE.findall(entry.description.lower())}
            return 3 * len(wanted & name_words) + len(wanted & desc_words)

        ranked = sorted(pool, key=lambda e: (-score(e), e.name))
        return ranked[:limit]

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
                from jarvis.core import failsoft
                failsoft.suppress("core.tool_catalog:get_tool_declarations")
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


_JSON_TYPES = {
    "STRING": (str,), "INTEGER": (int,), "NUMBER": (int, float),
    "BOOLEAN": (bool,), "ARRAY": (list, tuple), "OBJECT": (dict,),
}


def schema_errors(entry: CatalogEntry, args: dict) -> list[str]:
    """Why ``args`` do not fit the tool's declared schema (empty list = fits).

    Checks required keys, unknown keys, basic types and enums. ``device`` is the
    caller's business (the registry layer adds it to every tool).
    """
    errors: list[str] = []
    schema = entry.parameters if isinstance(entry.parameters, dict) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), (list, tuple)) else []
    for key in required:
        if key not in args and key != "device":
            errors.append(f"missing required argument '{key}'")
    for key, value in args.items():
        if key == "device":
            continue
        spec = props.get(key)
        if spec is None:
            errors.append(f"unknown argument '{key}'")
            continue
        kind = str(spec.get("type", "")).upper() if isinstance(spec, dict) else ""
        allowed = _JSON_TYPES.get(kind)
        if allowed:
            bad_bool = isinstance(value, bool) and kind in ("INTEGER", "NUMBER")
            if bad_bool or not isinstance(value, allowed):
                errors.append(f"argument '{key}' must be {kind.lower()}")
                continue
        enum = spec.get("enum") if isinstance(spec, dict) else None
        if isinstance(enum, (list, tuple)) and enum and value not in enum:
            errors.append(f"argument '{key}' must be one of {list(enum)[:8]}")
    return errors


# -- process-wide hook ---------------------------------------------------------
# main.py registers a provider once the registries are discovered; the planner
# asks for it lazily. Without a provider there is simply no catalog.
_provider: Optional[Callable[[], ToolCatalog]] = None


def set_default_provider(provider: Optional[Callable[[], ToolCatalog]]) -> None:
    global _provider
    _provider = provider


def get_default_catalog() -> Optional[ToolCatalog]:
    """The current catalog, or None when no provider is set or it fails."""
    provider = _provider
    if provider is None:
        return None
    try:
        catalog = provider()
    except Exception:
        return None
    return catalog if isinstance(catalog, ToolCatalog) else None
