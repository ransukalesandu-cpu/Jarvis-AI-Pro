"""
Action discovery, validation, and dispatch — the built-in twin of plugin_loader.

Every actions/*.py that exposes a module-level ``TOOL`` dict is auto-discovered
here, exactly like a drop-in plugin, so main.py never has to hardcode a tool
declaration or a dispatch branch for it. Adding a new bundled action is then the
same one-file operation as writing a plugin: define ``TOOL`` and a handler.

``TOOL`` shape (see actions/open_app.py for a live example):

    TOOL = {
        "name":        "open_app",              # unique, ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$
        "description":  "...",                   # what Gemini reads to route the call
        "parameters":  {"type": "OBJECT", ...}, # Gemini function-declaration schema
        "handler":      open_app,                # the callable to run
    }

The handler is invoked through signature introspection: it receives ``parameters``
plus whichever of ``player`` / ``speak`` / ``response`` / ``session_memory`` /
``cancel_event`` it actually declares — so existing action signatures work unchanged.

Optional fields (see core/tool_runtime.py): ``risk`` ("read" | "write" |
"destructive", for the action log only), ``timeout`` (seconds), ``long_running``
(run as a background job and return a job id), and ``available`` (a callable;
the tool is hidden from Gemini while it returns False, e.g. until credentials
are configured). Every tool also gets an optional ``device`` argument.

A file may define several tools with ``TOOLS = [TOOL_A, TOOL_B]`` instead of
one ``TOOL``. Adding a tool is one new file in actions/ (or plugins/) and no
change anywhere else.

Discovery runs once at startup; import errors, validation errors, and name
collisions are logged and the offending file is skipped — they NEVER raise out
of discover_actions() and never abort the scan of the remaining files.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.tool_runtime import ToolMeta, meta_from_declaration

_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_DEFAULT_PARAMS = {"type": "OBJECT", "properties": {}}
_CTX_KEYS = ("player", "speak", "response", "session_memory", "cancel_event")


# A tool may declare that the model should NOT be held up waiting for it.
# `behavior` goes to the API with the declaration; `scheduling` decides when the
# eventual result is allowed back into the conversation:
#   WHEN_IDLE  — wait for a gap in the speech (the sane default)
#   SILENT     — record it, do not prompt a reply (the tool already announced)
#   INTERRUPT  — cut in immediately (only when the answer cannot wait)
_BEHAVIORS = ("BLOCKING", "NON_BLOCKING")
_SCHEDULING = ("WHEN_IDLE", "SILENT", "INTERRUPT")


def _opt_upper(value, allowed: tuple[str, ...]) -> Optional[str]:
    v = str(value or "").strip().upper()
    return v if v in allowed else None


@dataclass
class ActionRecord:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: dict(_DEFAULT_PARAMS))
    handler: Optional[Callable] = None
    file: str = ""
    valid: bool = False
    error: str = ""
    behavior: Optional[str] = None     # None = the API's default (blocking)
    scheduling: Optional[str] = None   # None = the API's default (WHEN_IDLE)
    meta: ToolMeta = field(default_factory=ToolMeta)
    available: Optional[Callable[[], bool]] = None


def _is_available(rec) -> bool:
    check = getattr(rec, "available", None)
    if check is None:
        return True
    try:
        return bool(check())
    except Exception:
        return False


class ActionRegistry:
    def __init__(self, actions: dict[str, ActionRecord], logger: Callable[[str], None]):
        self._actions = actions          # name -> ActionRecord, VALID entries only
        self._all_records: list[ActionRecord] = []
        self._logger = logger

    # -- called by main.py at LiveConnectConfig build time --
    def get_tool_declarations(self) -> list[dict]:
        out = []
        for rec in self._actions.values():
            if not _is_available(rec):
                continue
            decl = {"name": rec.name, "description": rec.description,
                    "parameters": rec.parameters}
            if rec.behavior:
                decl["behavior"] = rec.behavior
            out.append(decl)
        return out

    def has(self, name: str) -> bool:
        return name in self._actions

    def scheduling(self, name: str) -> Optional[str]:
        """How this action's result should re-enter the conversation, if it said."""
        rec = self._actions.get(name)
        return rec.scheduling if rec else None

    def names(self) -> set[str]:
        return set(self._actions.keys())

    def meta(self, name: str) -> Optional[ToolMeta]:
        rec = self._actions.get(name)
        return rec.meta if rec else None

    # -- called from _execute_tool (core/runtime/live_tools.py) --
    def run(self, name: str, parameters: dict, ctx: dict | None = None) -> str:
        rec = self._actions.get(name)
        if rec is None or not rec.valid:
            return f"Action '{name}' is not available."
        try:
            return _call_handler(rec.handler, parameters, ctx or {}) or "Done."
        except Exception as e:
            self._logger(f"Action '{name}' crashed during run(): {e}")
            traceback.print_exc()
            return f"Tool '{name}' failed: {e}"


def _call_handler(fn: Callable, parameters: dict, ctx: dict) -> str:
    """Invoke the handler passing only the context kwargs it actually declares
    (or all of them if it has **kwargs), so each action's existing signature
    works unchanged."""
    sig = inspect.signature(fn)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    kwargs = {}
    for key in _CTX_KEYS:
        if has_var_kw or key in sig.parameters:
            kwargs[key] = ctx.get(key)
    return fn(parameters=parameters, **kwargs)


def _validate(module, filename: str, tool: dict | None = None) -> ActionRecord:
    """Returns an ActionRecord; .valid=False + .error set on any problem. Never raises."""
    if tool is None:
        tool = getattr(module, "TOOL", None)
    if not isinstance(tool, dict):
        return ActionRecord(name=Path(filename).stem, file=filename,
                            error="No module-level TOOL dict (not a discoverable action).")

    name = tool.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return ActionRecord(name=str(name or Path(filename).stem), file=filename,
                            error="TOOL['name'] missing or not a valid identifier.")

    description = tool.get("description")
    if not isinstance(description, str) or not description.strip():
        return ActionRecord(name=name, file=filename,
                            error="TOOL['description'] missing or empty.")

    parameters = tool.get("parameters", _DEFAULT_PARAMS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        return ActionRecord(name=name, file=filename,
                            error="TOOL['parameters'] must be a dict with \"type\": \"OBJECT\".")

    handler = tool.get("handler")
    if not callable(handler):
        return ActionRecord(name=name, file=filename,
                            error="TOOL['handler'] missing or not callable.")

    available = tool.get("available")
    return ActionRecord(name=name, description=description.strip(), parameters=parameters,
                        handler=handler, file=filename, valid=True, error="",
                        behavior=_opt_upper(tool.get("behavior"), _BEHAVIORS),
                        scheduling=_opt_upper(tool.get("scheduling"), _SCHEDULING),
                        meta=meta_from_declaration(tool),
                        available=available if callable(available) else None)


def _tool_dicts(module) -> list:
    """The tool declarations a module offers: TOOL, or the TOOLS list."""
    tool = getattr(module, "TOOL", None)
    if tool is not None:
        return [tool]
    tools = getattr(module, "TOOLS", None)
    if isinstance(tools, (list, tuple)):
        return list(tools)
    return []


def _collect_triggers(module, filename: str, logger: Callable[[str], None]) -> None:
    """Register a module's ``TRIGGERS`` list (see core/triggers.py). Never raises."""
    rows = getattr(module, "TRIGGERS", None)
    if not rows:
        return
    from core.triggers import get_trigger_registry
    registry = get_trigger_registry()
    for row in rows if isinstance(rows, (list, tuple)) else [rows]:
        try:
            trig = registry.register(dict(row), source="file")
            logger(f"Trigger registered: {trig.name} ({filename})")
        except Exception as exc:
            logger(f"Trigger rejected in {filename}: {exc}")


def discover_actions(actions_dir: Path, reserved_names: set[str] | None = None,
                     logger: Callable[[str], None] = print) -> ActionRegistry:
    """
    Scans actions_dir for *.py files (skips files starting with '_'). A file is
    only treated as an action if it exposes a module-level TOOL dict; files
    without one (shared helpers, capture-only modules) are silently ignored.
    Import/validation errors and name collisions are logged and the file is
    skipped — they NEVER raise out of this function.
    """
    reserved = reserved_names or set()
    actions_dir.mkdir(parents=True, exist_ok=True)
    valid: dict[str, ActionRecord] = {}
    all_records: list[ActionRecord] = []

    files = sorted(actions_dir.glob("*.py"), key=lambda p: p.name)  # deterministic order
    for path in files:
        if path.name.startswith("_"):
            continue
        try:
            module_name = f"actions.{path.stem}"
            # Reuse the already-imported module when present so handlers are the
            # same objects the rest of the app holds.
            module = sys.modules.get(module_name)
            if module is None:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise ImportError("could not build import spec")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise

            _collect_triggers(module, path.name, logger)
            tool_dicts = _tool_dicts(module)
            if not tool_dicts:
                continue   # not an action file — a helper/capture-only module

            records = []
            for tool in tool_dicts:
                rec = _validate(module, path.name, tool)
                if rec.valid and rec.name in reserved:
                    rec = ActionRecord(name=rec.name, file=path.name,
                                       error=f"Name '{rec.name}' collides with a reserved core tool — rejected.")
                elif rec.valid and rec.name in valid:
                    other = valid[rec.name].file
                    rec = ActionRecord(name=rec.name, file=path.name,
                                       error=f"Name '{rec.name}' already used by action '{other}' — rejected.")
                records.append(rec)
                if rec.valid:
                    valid[rec.name] = rec

        except Exception as e:
            records = [ActionRecord(name=path.stem, file=path.name,
                                    error=f"Failed to load: {e}")]
            traceback.print_exc()

        for rec in records:
            all_records.append(rec)
            if rec.valid:
                logger(f"Action loaded: {rec.name} ({path.name})")
            else:
                # Only log a rejection if the file actually tried to be an action.
                logger(f"Action rejected: {path.name} — {rec.error}")

    registry = ActionRegistry(valid, logger)
    registry._all_records = all_records
    logger(f"Action discovery complete: {len(valid)} active.")
    return registry
