"""An in-memory Windows desktop for tests: never touches the real system.

Apps: Notepad (edit box, File menu, "save changes?" dialog on close), Calculator
(digit/operator buttons and a display), a login form (with a password field and
a disabled button) and a "Settings" app whose Apply button stays disabled.
Behaviour is deliberately close to the real apps so controller logic
(verification, dialogs, ambiguity, unavailable controls) is exercised.
"""
from __future__ import annotations

import itertools
import re
import threading
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from jarvis.computer_control.windows.backend import BackendError, ElementGone
from jarvis.computer_control.windows.model import AppInfo, ElementInfo, ProcessInfo, Rect, WindowInfo


@dataclass
class _El:
    name: str
    control_type: str
    automation_id: str = ""
    enabled: bool = True
    is_password: bool = False
    value: Optional[str] = None
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 80, 24))
    items: tuple = ()
    on_invoke: Optional[Callable[[], None]] = None
    toggle_state: str = "off"


@dataclass
class _Win:
    handle: int
    title: str
    pid: int
    process_name: str
    class_name: str
    rect: Rect
    elements: list = field(default_factory=list)
    minimized: bool = False
    maximized: bool = False
    on_close: Optional[Callable[["_Win"], bool]] = None   # return False to veto (dialog shown)
    menus: dict = field(default_factory=dict)              # "File->Save As" -> callable


class FakeDesktop:
    name = "fake"

    def __init__(self, *, screen: tuple[int, int] = (1920, 1080), slow_launch: int = 0) -> None:
        self._lock = threading.RLock()
        self._pids = itertools.count(4000)
        self._handles = itertools.count(0x10000)
        self._windows: dict[int, _Win] = {}
        self._procs: dict[int, ProcessInfo] = {}
        self._active: Optional[int] = None
        self._screen = screen
        self.slow_launch = slow_launch      # launches whose window appears after N windows() calls
        self._pending: list[tuple[int, Callable[[], None]]] = []
        self.calls: list[tuple] = []
        self.sent_text: list[tuple[int, str]] = []
        self.hotkeys: list[tuple[int, tuple]] = []
        self.files: dict[str, str] = {}
        self._apps = {
            "notepad": AppInfo("Notepad", "notepad.exe", "fake"),
            "calculator": AppInfo("Calculator", "calc.exe", "fake"),
            "contoso login": AppInfo("Contoso Login", "contoso.exe", "fake"),
            "settings app": AppInfo("Settings App", "settingsapp.exe", "fake"),
        }

    # ── discovery ─────────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        return True, ""

    def installed_apps(self) -> list[AppInfo]:
        return list(self._apps.values())

    def processes(self) -> list[ProcessInfo]:
        with self._lock:
            return list(self._procs.values())

    def screen_size(self) -> tuple[int, int]:
        return self._screen

    # ── launch / close ────────────────────────────────────────────────────
    def launch(self, target: str, args: list[str]) -> int:
        self.calls.append(("launch", target, tuple(args)))
        key = target.lower().removesuffix(".exe")
        builders = {"notepad": self._make_notepad, "calc": self._make_calculator,
                    "contoso": self._make_login, "settingsapp": self._make_settings}
        build = builders.get(key)
        if build is None:
            raise BackendError(f"'{target}' is not installed")
        with self._lock:
            pid = next(self._pids)
            self._procs[pid] = ProcessInfo(pid, f"{key}.exe", f"C:\\Fake\\{key}.exe")
        if self.slow_launch:
            self._pending.append((self.slow_launch, lambda: build(pid, args)))
        else:
            build(pid, args)
        return pid

    def terminate(self, pid: int, force: bool = False) -> bool:
        self.calls.append(("terminate", pid, force))
        with self._lock:
            if pid not in self._procs:
                return False
            for handle in [h for h, w in self._windows.items() if w.pid == pid]:
                self._windows.pop(handle, None)
            self._procs.pop(pid, None)
            if self._active not in self._windows:
                self._active = next(iter(self._windows), None)
            return True

    # ── windows ───────────────────────────────────────────────────────────
    def _tick(self) -> None:
        ready = []
        for i, (left, build) in enumerate(self._pending):
            self._pending[i] = (left - 1, build)
            if left - 1 <= 0:
                ready.append(i)
        for i in reversed(ready):
            _, build = self._pending.pop(i)
            build()

    def windows(self) -> list[WindowInfo]:
        with self._lock:
            self._tick()
            return [self._info(w) for w in self._windows.values()]

    def _info(self, w: _Win) -> WindowInfo:
        return WindowInfo(handle=w.handle, title=w.title, pid=w.pid, process_name=w.process_name,
                          class_name=w.class_name, rect=w.rect, visible=not w.minimized,
                          minimized=w.minimized, maximized=w.maximized,
                          active=self._active == w.handle)

    def _win(self, handle: int) -> _Win:
        w = self._windows.get(int(handle))
        if w is None:
            raise ElementGone(f"window {handle} no longer exists")
        return w

    def activate(self, handle: int) -> None:
        with self._lock:
            w = self._win(handle)
            w.minimized = False
            self._active = w.handle
            self.calls.append(("activate", handle))

    def set_window_state(self, handle: int, state: str) -> None:
        with self._lock:
            w = self._win(handle)
            if state == "minimize":
                w.minimized, w.maximized = True, False
                if self._active == w.handle:
                    self._active = None
            elif state == "maximize":
                w.minimized, w.maximized = False, True
                w.rect = Rect(0, 0, *self._screen)
            elif state == "restore":
                w.minimized = w.maximized = False
            else:
                raise BackendError(f"unknown window state {state!r}")

    def move_resize(self, handle: int, left: int, top: int, width: int, height: int) -> None:
        with self._lock:
            w = self._win(handle)
            w.maximized = False
            w.rect = Rect(left, top, left + width, top + height)

    def close_window(self, handle: int) -> None:
        with self._lock:
            w = self._win(handle)
            if w.on_close is not None and w.on_close(w) is False:
                return
            self._remove_window(w)

    def _remove_window(self, w: _Win) -> None:
        self._windows.pop(w.handle, None)
        if not any(x.pid == w.pid for x in self._windows.values()):
            self._procs.pop(w.pid, None)
        if self._active == w.handle:
            self._active = next(reversed(list(self._windows)), None) if self._windows else None

    # ── elements ──────────────────────────────────────────────────────────
    def _ref(self, w: _Win, i: int) -> str:
        return f"{w.handle}:{i}"

    def _el(self, ref: str) -> tuple[_Win, _El]:
        try:
            handle_s, index_s = str(ref).split(":", 1)
            w = self._win(int(handle_s))
            return w, w.elements[int(index_s)]
        except (ValueError, IndexError) as exc:
            raise ElementGone(f"control {ref} no longer exists") from exc

    def elements(self, handle: int, depth: int = 6, limit: int = 400) -> list[ElementInfo]:
        with self._lock:
            w = self._win(handle)
            out = []
            for i, e in enumerate(w.elements[:limit]):
                out.append(ElementInfo(
                    ref=self._ref(w, i), name=e.name, control_type=e.control_type,
                    automation_id=e.automation_id, rect=e.rect, enabled=e.enabled,
                    is_password=e.is_password,
                    value=None if e.is_password else e.value, window_handle=w.handle,
                    focusable=e.control_type in ("Edit", "Button", "ComboBox", "CheckBox")))
            return out

    def _require_enabled(self, e: _El) -> None:
        if not e.enabled:
            raise BackendError(f"'{e.name}' is disabled")

    def click(self, ref: str) -> None:
        self.invoke(ref)

    def invoke(self, ref: str) -> None:
        with self._lock:
            w, e = self._el(ref)
            self._require_enabled(e)
            self.calls.append(("invoke", w.title, e.name))
            if e.on_invoke:
                e.on_invoke()

    def set_text(self, ref: str, text: str) -> None:
        with self._lock:
            w, e = self._el(ref)
            self._require_enabled(e)
            if e.control_type not in ("Edit", "Document", "ComboBox"):
                raise BackendError(f"'{e.name}' does not accept text")
            e.value = str(text)
            self.calls.append(("set_text", w.title, e.name, "***" if e.is_password else text))

    def get_value(self, ref: str) -> Optional[str]:
        with self._lock:
            _w, e = self._el(ref)
            return None if e.is_password else e.value

    def password_length(self, ref: str) -> int:
        """Test hook: the fake keeps the password so a test can check it arrived."""
        with self._lock:
            return len(self._el(ref)[1].value or "")

    def select(self, ref: str, item: str) -> None:
        with self._lock:
            _w, e = self._el(ref)
            self._require_enabled(e)
            match = [i for i in e.items if str(i).casefold() == str(item).casefold()]
            if not match:
                raise BackendError(f"'{item}' is not an option of '{e.name}'")
            e.value = match[0]

    def toggle(self, ref: str) -> str:
        with self._lock:
            _w, e = self._el(ref)
            self._require_enabled(e)
            e.toggle_state = "off" if e.toggle_state == "on" else "on"
            return e.toggle_state

    def menu_select(self, handle: int, path: str) -> None:
        with self._lock:
            w = self._win(handle)
            parts = re.split(r"\s*-?>\s*", str(path))
            key = "->".join(p.strip().casefold() for p in parts if p.strip())
            fn = w.menus.get(key)
            if fn is None:
                raise BackendError(f"menu item '{path}' was not found in '{w.title}'")
            self.calls.append(("menu", w.title, key))
            fn()

    def send_text(self, handle: int, text: str) -> None:
        with self._lock:
            w = self._win(handle)
            self.sent_text.append((w.handle, text))
            for e in w.elements:
                if e.control_type in ("Edit", "Document") and e.automation_id == "focus":
                    e.value = (e.value or "") + text

    def send_hotkey(self, handle: int, keys: list[str]) -> None:
        with self._lock:
            w = self._win(handle)
            self.hotkeys.append((w.handle, tuple(keys)))
            if tuple(k.lower() for k in keys) == ("ctrl", "s"):
                fn = w.menus.get("file->save")
                if fn:
                    fn()

    # ── app builders ──────────────────────────────────────────────────────
    def _add(self, pid: int, title: str, process: str, cls: str, elements: list,
             rect: Optional[Rect] = None) -> _Win:
        rect = rect or Rect(100, 100, 900, 700)
        w = _Win(next(self._handles), title, pid, process, cls, rect, elements)
        self._windows[w.handle] = w
        self._active = w.handle
        return w

    def _make_notepad(self, pid: int, args) -> None:
        path = str(args[0]) if args else ""
        name = path.replace("/", "\\").rsplit("\\", 1)[-1] if path else "Untitled"
        edit = _El("Text Editor", "Edit", "focus", value=self.files.get(path, ""),
                   rect=Rect(100, 150, 900, 680))
        w = self._add(pid, f"{name} - Notepad", "notepad.exe", "Notepad", [
            edit, _El("File", "MenuItem"), _El("Edit", "MenuItem"), _El("Format", "MenuItem")])
        saved = {"text": edit.value}

        def save():
            if not path:
                raise BackendError("Save As dialog not supported in the fake")
            self.files[path] = edit.value or ""
            saved["text"] = edit.value

        def on_close(win: _Win) -> bool:
            if edit.value == saved["text"]:
                return True
            self._save_prompt(win, save)
            return False

        w.on_close = on_close
        w.menus = {"file->save": save}

    def _save_prompt(self, parent: _Win, save) -> None:
        dialog: dict = {}

        def answer(do_save: bool, close_parent: bool):
            def run():
                if do_save:
                    save()
                self._remove_window(dialog["w"])
                if close_parent:
                    self._remove_window(parent)
                else:
                    self._active = parent.handle
            return run

        dialog["w"] = self._add(parent.pid, "Notepad", parent.process_name, "#32770", [
            _El("Do you want to save changes?", "Text"),
            _El("Save", "Button", on_invoke=answer(True, True)),
            _El("Don't Save", "Button", on_invoke=answer(False, True)),
            _El("Cancel", "Button", on_invoke=answer(False, False)),
        ], rect=Rect(400, 300, 760, 460))

    def _make_calculator(self, pid: int, args) -> None:
        state = {"display": "0", "acc": None, "op": None, "fresh": True}
        display = _El("Display is 0", "Text", "CalculatorResults")

        def show():
            display.name = f"Display is {state['display']}"
            display.value = state["display"]

        def digit(d):
            def run():
                state["display"] = d if state["fresh"] or state["display"] == "0" else state["display"] + d
                state["fresh"] = False
                show()
            return run

        def op(sym):
            def run():
                equals()
                state["acc"], state["op"], state["fresh"] = float(state["display"]), sym, True
            return run

        def equals():
            if state["op"] and state["acc"] is not None:
                b = float(state["display"])
                a = state["acc"]
                result = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else float("nan")}[state["op"]]
                state["display"] = str(int(result)) if result == int(result) else str(result)
                state["acc"], state["op"], state["fresh"] = None, None, True
                show()

        names = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
        elements = [display] + [_El(n, "Button", f"num{i}Button", on_invoke=digit(str(i)))
                                for i, n in enumerate(names)]
        elements += [_El("Plus", "Button", "plusButton", on_invoke=op("+")),
                     _El("Minus", "Button", "minusButton", on_invoke=op("-")),
                     _El("Multiply by", "Button", "multiplyButton", on_invoke=op("*")),
                     _El("Equals", "Button", "equalButton", on_invoke=equals)]
        self._add(pid, "Calculator", "calc.exe", "ApplicationFrameWindow", elements,
                  rect=Rect(200, 200, 520, 720))

    def _make_login(self, pid: int, args) -> None:
        status = _El("", "Text", "status")
        user = _El("Username", "Edit", "user", value="")
        pwd = _El("Password", "Edit", "pass", is_password=True, value="")

        def sign_in():
            status.name = "Signed in" if user.value and pwd.value else "Missing credentials"

        self._add(pid, "Contoso Login", "contoso.exe", "Contoso", [
            user, pwd, _El("Sign in", "Button", "signin", on_invoke=sign_in), status,
            _El("Register", "Button", "register", enabled=False),
            _El("Theme", "ComboBox", "theme", value="Light", items=("Light", "Dark")),
            _El("Remember me", "CheckBox", "remember")])

    def _make_settings(self, pid: int, args) -> None:
        self._add(pid, "Settings App", "settingsapp.exe", "SettingsApp", [
            _El("Apply", "Button", "apply", enabled=False), _El("OK", "Button", "ok"),
            _El("OK", "Button", "ok2")])

    # ── test helpers ──────────────────────────────────────────────────────
    def element_named(self, title_contains: str, name: str) -> _El:
        for w in self._windows.values():
            if title_contains.casefold() in w.title.casefold():
                for e in w.elements:
                    if e.name == name:
                        return e
        raise KeyError(name)

    def rename_window(self, handle: int, title: str) -> None:
        self._windows[handle] = replace(self._windows[handle], title=title)
