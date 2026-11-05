"""ToolSpecs for Windows native control (registered by computer_control.tools).

Four tools keep the model's tool list short; ``op`` picks the operation and
``action_for`` maps it to the policy action, so each operation gets its own
risk level (e.g. ``cc_app`` op=launch is LOW, op=kill is HIGH).
"""
from __future__ import annotations

from typing import Any, Mapping

from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.runner import ActionContext, ActionOutcome
from jarvis.computer_control.windows.controller import get_controller
from jarvis.computer_control.windows.model import ElementQuery, WindowQuery

S, INT, A = "STRING", "INTEGER", "ARRAY"

_WINDOW_PROPS = {
    "window": {"type": S, "description": "Part of the window title, e.g. 'Notepad'. Empty = active window."},
    "window_title": {"type": S, "description": "Exact window title."},
    "process": {"type": S, "description": "Process name, e.g. 'notepad.exe'."},
    "handle": {"type": INT, "description": "Window handle from an earlier result."},
}
_ELEMENT_PROPS = {
    "name": {"type": S, "description": "Accessible name of the control, e.g. 'Save'."},
    "name_contains": {"type": S, "description": "Part of the control name."},
    "automation_id": {"type": S, "description": "UI Automation id."},
    "control_type": {"type": S, "description": "Button, Edit, MenuItem, CheckBox, ComboBox, ..."},
    "ref": {"type": S, "description": "Control ref from an earlier result."},
    "index": {"type": INT, "description": "Which match to use when several match (0-based)."},
    "expect_window": {"type": S, "description": "Window title expected afterwards (verification)."},
    "expect_text": {"type": S, "description": "Text expected in the window afterwards (verification)."},
    "expect_timeout": {"type": INT, "description": "Seconds to wait for the expectation (default 5)."},
}

APP_OPS = {"list_installed": "app.list", "list_running": "app.running", "launch": "app.launch",
           "state": "app.state", "close": "app.close", "kill": "app.kill"}
WINDOW_OPS = {"list": "window.list", "activate": "window.activate", "minimize": "window.minimize",
              "maximize": "window.maximize", "restore": "window.restore", "move": "window.move",
              "resize": "window.resize", "close": "window.close", "inspect": "window.inspect",
              "wait": "window.wait"}
CONTROL_OPS = {"find": "element.find", "read": "element.read", "invoke": "element.invoke",
               "click": "element.click", "set_text": "element.set_text", "select": "element.select",
               "toggle": "element.toggle", "menu": "menu.select", "wait": "element.wait",
               "type": "input.type", "hotkey": "input.hotkey"}
POINTER_OPS = {"click": "input.click", "double_click": "input.double_click",
               "right_click": "input.right_click", "move": "input.move", "drag": "input.drag",
               "scroll": "input.scroll", "position": "input.position", "type": "input.type",
               "hotkey": "input.hotkey"}


def _op(params: Mapping[str, Any], table: dict, default: str) -> str:
    op = str(params.get("op") or default).strip().lower()
    return table.get(op, "unknown")


def _int(value, default=None):
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _keys(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(k) for k in value]
    return [k for k in str(value or "").replace(" ", "").split("+") if k]


def _app(ctx: ActionContext) -> ActionOutcome:
    p, c = ctx.params, get_controller()
    op = str(p.get("op") or "list_running").lower()
    if op == "list_installed":
        return c.list_installed(ctx, str(p.get("query") or ""))
    if op == "list_running":
        return c.list_running(ctx)
    if op == "launch":
        args = p.get("args") or []
        return c.launch(ctx, str(p.get("name") or ""), args if isinstance(args, list) else [str(args)])
    if op == "state":
        return c.app_state(ctx, str(p.get("name") or ""), _int(p.get("pid")))
    if op in ("close", "kill"):
        return c.close_app(ctx, str(p.get("name") or ""), _int(p.get("pid")), force=op == "kill")
    return ActionOutcome(False, f"Unknown op '{op}'.")


def _window(ctx: ActionContext) -> ActionOutcome:
    p, c = ctx.params, get_controller()
    op = str(p.get("op") or "list").lower()
    wq = WindowQuery.from_params(p)
    if op == "list":
        return c.list_windows(ctx, wq)
    if op == "activate":
        return c.activate(ctx, wq)
    if op in ("minimize", "maximize", "restore"):
        return c.set_state(ctx, wq, op)
    if op in ("move", "resize"):
        return c.move_resize(ctx, wq, _int(p.get("left")), _int(p.get("top")),
                             _int(p.get("width")), _int(p.get("height")))
    if op == "close":
        return c.close_window(ctx, wq)
    if op == "inspect":
        return c.inspect_window(ctx, wq, _int(p.get("depth"), 6))
    if op == "wait":
        return c.wait_window(ctx, wq, float(p.get("timeout") or 10))
    return ActionOutcome(False, f"Unknown op '{op}'.")


def _control(ctx: ActionContext) -> ActionOutcome:
    p, c = ctx.params, get_controller()
    op = str(p.get("op") or "find").lower()
    wq, eq = WindowQuery.from_params(p), ElementQuery.from_params(p)
    if op == "find":
        return c.find(ctx, wq, eq)
    if op == "read":
        return c.read(ctx, wq, eq)
    if op in ("invoke", "click"):
        return c.invoke(ctx, wq, eq, p, method=op)
    if op == "set_text":
        return c.set_text(ctx, wq, eq, str(p.get("text") or ""))
    if op == "select":
        return c.select(ctx, wq, eq, str(p.get("item") or ""))
    if op == "toggle":
        return c.toggle(ctx, wq, eq)
    if op == "menu":
        return c.menu(ctx, wq, str(p.get("path") or ""), p)
    if op == "wait":
        return c.wait_element(ctx, wq, eq, float(p.get("timeout") or 10))
    if op == "type":
        return c.type_text(ctx, wq, str(p.get("text") or ""))
    if op == "hotkey":
        return c.hotkey(ctx, wq, _keys(p.get("keys")))
    return ActionOutcome(False, f"Unknown op '{op}'.")


def _pointer(ctx: ActionContext) -> ActionOutcome:
    return get_controller().pointer(ctx, str(ctx.params.get("op") or "position").lower(), ctx.params)


def _enrich_control(params: dict) -> dict:
    """Add what will really be touched, for the policy: the target window's title
    as ``app`` (typing into a shell is HIGH) and the control's accessible name as
    ``label`` (a "Delete" button is HIGH however it was referenced)."""
    op = str(params.get("op") or "").lower()
    if op not in ("invoke", "click", "toggle", "select", "set_text", "type", "hotkey", "menu"):
        return params
    controller = get_controller()
    try:
        window = controller.window(WindowQuery.from_params(params))
    except Exception:
        return params
    params["app"] = window.title
    if op in ("invoke", "click", "toggle", "select", "set_text"):
        try:
            element = controller.element(window, ElementQuery.from_params(params))
        except Exception:
            return params
        params["label"] = element.name
        if element.is_password:
            params["is_password"] = True      # redacted in approval details and the log
    return params


def _enrich_pointer(params: dict) -> dict:
    """Coordinates from the model are never trusted, and keys go to the focused window.

    * click / double_click / right_click / drag at model-supplied coordinates are
      HIGH (owner approval): use cc_control or cc_screen (which locates the
      target itself) for anything routine;
    * type / hotkey: the policy sees the real foreground window title (typing into
      a shell is HIGH); if it cannot be read, fail closed to HIGH.
    """
    op = str(params.get("op") or "").lower()
    params.pop("_trusted_source", None)
    if op in ("click", "double_click", "right_click", "drag"):
        params["requested_level"] = "high"
    if op in ("type", "hotkey"):
        try:
            params["app"] = get_controller().window(WindowQuery()).title
        except Exception:
            params["requested_level"] = "high"
    return params


def register(reg: SpecRegistry) -> None:
    reg.register(ToolSpec(
        id="cc_app", action="app.list",
        description=("Windows apps: list_installed, list_running, launch (opens it and waits for its "
                     "window), state, close (graceful; reports save dialogs), kill (force, needs approval)."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(APP_OPS)},
            "name": {"type": S, "description": "App name, e.g. 'Notepad', 'Chrome', or an .exe path."},
            "args": {"type": A, "items": {"type": S}, "description": "Launch arguments (e.g. a file)."},
            "pid": {"type": INT}, "query": {"type": S, "description": "Filter for list_installed."}},
            "required": ["op"]},
        handler=_app, timeout=30.0, action_for=lambda p: _op(p, APP_OPS, "list_running"),
        summary_for=lambda p: f"{p.get('op')} app {p.get('name') or p.get('pid') or ''}".strip()))
    reg.register(ToolSpec(
        id="cc_window", action="window.list",
        description=("Windows windows: list, activate, minimize, maximize, restore, move/resize "
                     "(left, top, width, height), close (reports dialogs), inspect (list controls), wait."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(WINDOW_OPS)}, **_WINDOW_PROPS,
            "left": {"type": INT}, "top": {"type": INT}, "width": {"type": INT}, "height": {"type": INT},
            "depth": {"type": INT}, "timeout": {"type": INT}}, "required": ["op"]},
        handler=_window, timeout=30.0, action_for=lambda p: _op(p, WINDOW_OPS, "list")))
    reg.register(ToolSpec(
        id="cc_control", action="element.find",
        description=("Controls inside a window via UI Automation (preferred over coordinates): find, read, "
                     "invoke/click a button, set_text, select an item, toggle, menu (path 'File->Save'), "
                     "wait, type text or press a hotkey into the window."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(CONTROL_OPS)}, **_WINDOW_PROPS, **_ELEMENT_PROPS,
            "text": {"type": S}, "item": {"type": S}, "path": {"type": S},
            "keys": {"type": S, "description": "Shortcut like 'ctrl+s'."}, "timeout": {"type": INT}},
            "required": ["op"]},
        handler=_control, timeout=30.0, action_for=lambda p: _op(p, CONTROL_OPS, "find"),
        enrich=_enrich_control,
        summary_for=lambda p: f"{p.get('op')} '{p.get('name') or p.get('ref') or ''}' in "
                              f"'{p.get('window') or 'active window'}'"))
    reg.register(ToolSpec(
        id="cc_pointer", action="input.position",
        description=("Fallback mouse/keyboard by screen coordinates, only when no control can be found: "
                     "click, double_click, right_click, move, drag, scroll, position, type, hotkey. "
                     "Coordinates from screen analysis need source, confidence and fingerprint."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(POINTER_OPS)}, "x": {"type": INT}, "y": {"type": INT},
            "to_x": {"type": INT}, "to_y": {"type": INT}, "amount": {"type": INT},
            "button": {"type": S}, "text": {"type": S}, "keys": {"type": S},
            "source": {"type": S, "description": "owner | accessibility | ocr | vision | model"},
            "confidence": {"type": "NUMBER"}, "fingerprint": {"type": INT},
            "target": {"type": S, "description": "What is being clicked (for the safety check)."}},
            "required": ["op"]},
        handler=_pointer, timeout=20.0, action_for=lambda p: _op(p, POINTER_OPS, "position"),
        enrich=_enrich_pointer))
