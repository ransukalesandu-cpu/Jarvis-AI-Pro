"""The Windows Controller: one API over a swappable backend.

Every public method takes the runner's :class:`ActionContext` (stop checks,
interruptible waits) and returns an :class:`ActionOutcome` whose ``verified``
field says whether the effect was checked:

* launch → a window of the new process appeared;
* activate → the window is in the foreground;
* move/resize/min/max/restore → the window reports the new state/geometry;
* close → the window is gone, or the dialog that blocked it is reported;
* set_text → the value reads back (password fields are never read back);
* select/toggle → the new state reads back;
* click/invoke/menu → verified only when the caller names an expectation
  (``expect_window`` / ``expect_text``), otherwise reported as unchecked.

Expected failures (not found, ambiguous, disabled/unavailable control, window
gone) come back as ``ok=False`` outcomes with a sentence JARVIS can say; they
are never retried here (the orchestrator decides about recovery).

Accessibility first: controls are found by name / automation id / control type
through UI Automation. Coordinates are only used through
:class:`fallback_input.FallbackInput`, with its safeguards.
"""
from __future__ import annotations

import time
from typing import Callable, Iterable, Optional

from jarvis.computer_control.runner import ActionContext, ActionOutcome
from jarvis.computer_control.windows.backend import BackendError, WindowsBackend, get_backend
from jarvis.computer_control.windows.fallback_input import FallbackInput, InputRefused, Target
from jarvis.computer_control.windows.model import (
    AppInfo, ElementInfo, ElementQuery, WindowInfo, WindowQuery,
)

DIALOG_CLASSES = frozenset({"#32770", "NUIDialog", "Popup"})
_MAX_LIST = 60


class NotFound(BackendError):
    pass


class Ambiguous(BackendError):
    pass


def _fail(message: str, **data) -> ActionOutcome:
    return ActionOutcome(ok=False, message=message, data=data, verified=False)


def _alias_target(name: str) -> str:
    try:
        from jarvis.actions.open_app import _APP_ALIASES
    except Exception:
        return ""
    entry = _APP_ALIASES.get(name.casefold().strip())
    return str(entry.get("Windows", "")) if entry else ""


class WindowsController:
    def __init__(self, backend: WindowsBackend | None = None, fallback: FallbackInput | None = None,
                 *, launch_timeout: float = 15.0, poll: float = 0.25,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._backend = backend
        self._fallback = fallback
        self.launch_timeout = launch_timeout
        self.poll = poll
        self._clock = clock

    @property
    def backend(self) -> WindowsBackend:
        return self._backend or get_backend()

    @property
    def fallback(self) -> FallbackInput:
        if self._fallback is None:
            self._fallback = FallbackInput()
        return self._fallback

    # ── internal helpers ─────────────────────────────────────────────────
    def _guard(self, fn: Callable[[], ActionOutcome]) -> ActionOutcome:
        try:
            return fn()
        except (NotFound, Ambiguous, InputRefused) as exc:
            return _fail(str(exc))
        except BackendError as exc:
            return _fail(str(exc))

    def _wait_until(self, ctx: ActionContext, predicate: Callable[[], object],
                    timeout: float) -> object:
        deadline = self._clock() + max(0.0, timeout)
        while True:
            ctx.check()
            value = predicate()
            if value:
                return value
            if self._clock() >= deadline:
                return None
            ctx.wait(self.poll)

    def windows(self, query: WindowQuery | None = None) -> list[WindowInfo]:
        found = self.backend.windows()
        if query is None or query.empty():
            return [w for w in found if w.title or w.visible]
        return [w for w in found if query.matches(w)]

    def window(self, query: WindowQuery) -> WindowInfo:
        if query.empty():
            active = [w for w in self.backend.windows() if w.active]
            if active:
                return active[0]
            raise NotFound("No window is active; name the window to use.")
        matches = self.windows(query)
        if not matches:
            raise NotFound(f"No window matches {query.describe()}.")
        if len(matches) > 1:
            exact = [w for w in matches if query.title_contains and
                     w.title.casefold() == query.title_contains.casefold()]
            active = [w for w in matches if w.active]
            if len(exact) == 1:
                return exact[0]
            if len(active) == 1:
                return active[0]
            titles = "; ".join(f"'{w.title}' (handle {w.handle})" for w in matches[:5])
            raise Ambiguous(f"{len(matches)} windows match {query.describe()}: {titles}. "
                            "Say which one (title or handle).")
        return matches[0]

    def elements(self, window: WindowInfo, depth: int = 6) -> list[ElementInfo]:
        return self.backend.elements(window.handle, depth=depth)

    def element(self, window: WindowInfo, query: ElementQuery) -> ElementInfo:
        if query.empty():
            raise NotFound("Name the control to use (name, automation id or control type).")
        all_elements = self.elements(window)
        matches = [e for e in all_elements if query.matches(e)]
        if not matches and not query.include_disabled and not query.ref:
            loose = ElementQuery(**{**query.__dict__, "include_disabled": True})
            disabled = [e for e in all_elements if loose.matches(e)]
            if disabled:
                raise NotFound(f"'{disabled[0].name or query.describe()}' is in '{window.title}' but "
                               "is disabled right now (unavailable).")
        if not matches:
            raise NotFound(f"No control matching {query.describe()} in '{window.title}'.")
        if query.index is not None:
            if 0 <= query.index < len(matches):
                return matches[query.index]
            raise NotFound(f"Only {len(matches)} control(s) match {query.describe()}.")
        if len(matches) > 1:
            listed = "; ".join(e.short() for e in matches[:5])
            raise Ambiguous(f"{len(matches)} controls match {query.describe()} in '{window.title}': "
                            f"{listed}. Give an index or a more specific name.")
        return matches[0]

    @staticmethod
    def _mark_password(ctx: ActionContext, el: ElementInfo) -> None:
        if el.is_password:
            # the runner redacts the logged arguments from this same dict
            ctx.params["is_password"] = True

    def _expectation(self, ctx: ActionContext, window: WindowInfo, params: dict,
                     timeout: float = 5.0) -> tuple[Optional[bool], str]:
        try:
            timeout = max(0.0, min(float(params.get("expect_timeout") or timeout), 30.0))
        except (TypeError, ValueError):
            pass
        want_window = str(params.get("expect_window") or "").strip()
        want_text = str(params.get("expect_text") or "").strip()
        if not want_window and not want_text:
            return None, "no expected result was given, so the effect was not checked"

        def seen():
            if want_window:
                titles = [w.title for w in self.backend.windows()]
                if not any(want_window.casefold() in t.casefold() for t in titles):
                    return None
            if want_text:
                try:
                    names = [(e.name or "") + " " + (e.value or "") for e in self.elements(window)]
                except BackendError:
                    names = []
                if not any(want_text.casefold() in n.casefold() for n in names):
                    return None
            return True

        ok = self._wait_until(ctx, seen, timeout)
        what = " and ".join(x for x in (f"window '{want_window}'" if want_window else "",
                                        f"text '{want_text}'" if want_text else "") if x)
        return (True, f"saw {what}") if ok else (False, f"did not see {what} within {timeout:.0f}s")

    # ── applications ─────────────────────────────────────────────────────
    def resolve_app(self, name: str) -> Optional[AppInfo]:
        wanted = str(name or "").strip()
        if not wanted:
            return None
        apps = self.backend.installed_apps()
        for app in apps:
            if app.name.casefold() == wanted.casefold():
                return app
        alias = _alias_target(wanted)
        if alias:
            return AppInfo(wanted, alias, "alias")
        contains = [a for a in apps if wanted.casefold() in a.name.casefold()]
        if len(contains) == 1:
            return contains[0]
        if wanted.lower().endswith(".exe") or "\\" in wanted or "/" in wanted:
            return AppInfo(wanted, wanted, "path")
        return None

    def list_installed(self, ctx: ActionContext, query: str = "") -> ActionOutcome:
        ctx.check()
        apps = self.backend.installed_apps()
        if query:
            apps = [a for a in apps if query.casefold() in a.name.casefold()]
        names = [a.name for a in apps[:_MAX_LIST]]
        return ActionOutcome(True, f"{len(apps)} installed app(s)" + (f" match '{query}'" if query else "")
                             + (": " + ", ".join(names[:20]) if names else "."),
                             data={"apps": [a.as_dict() for a in apps[:_MAX_LIST]], "total": len(apps)})

    def list_running(self, ctx: ActionContext) -> ActionOutcome:
        ctx.check()
        wins = [w for w in self.backend.windows() if w.title and w.visible or w.minimized]
        apps: dict[str, list] = {}
        for w in wins:
            apps.setdefault(w.process_name or str(w.pid), []).append(w.title)
        summary = ", ".join(f"{k} ({len(v)})" for k, v in list(apps.items())[:20])
        return ActionOutcome(True, f"{len(apps)} app(s) with windows: {summary or 'none'}.",
                             data={"apps": apps, "windows": [w.as_dict() for w in wins[:_MAX_LIST]]},
                             verified=True, evidence="read from the live window list")

    def launch(self, ctx: ActionContext, name: str, args: Iterable[str] = ()) -> ActionOutcome:
        def run() -> ActionOutcome:
            ctx.check()
            app = self.resolve_app(name)
            if app is None:
                return _fail(f"I could not find an app called '{name}' on this computer.")
            before = {w.handle for w in self.backend.windows()}
            pid = self.backend.launch(app.target, [str(a) for a in args])
            stem = app.target.replace("/", "\\").rsplit("\\", 1)[-1].lower().removesuffix(".exe")

            def new_window():
                for w in self.backend.windows():
                    if w.handle in before or not w.title:
                        continue
                    if pid and w.pid == pid:
                        return w
                    proc = w.process_name.lower().removesuffix(".exe")
                    if proc == stem or app.name.casefold() in w.title.casefold():
                        return w
                return None

            window = self._wait_until(ctx, new_window, self.launch_timeout)
            if window is None:
                return ActionOutcome(True, f"Started {app.name}, but no window appeared within "
                                     f"{self.launch_timeout:.0f}s.", data={"pid": pid, "app": app.as_dict()},
                                     verified=False, evidence="no new window")
            return ActionOutcome(True, f"Opened {app.name}: '{window.title}'.",
                                 data={"pid": pid, "app": app.as_dict(), "window": window.as_dict()},
                                 verified=True, evidence=f"window '{window.title}' appeared")
        return self._guard(run)

    def app_state(self, ctx: ActionContext, name: str = "", pid: Optional[int] = None) -> ActionOutcome:
        ctx.check()
        wins = self.backend.windows()
        if pid is not None:
            mine = [w for w in wins if w.pid == pid]
        else:
            n = str(name).casefold().removesuffix(".exe")
            mine = [w for w in wins if w.process_name.casefold().removesuffix(".exe") == n
                    or (n and n in w.title.casefold())]
        running = bool(mine) or (pid is not None and any(p.pid == pid for p in self.backend.processes()))
        return ActionOutcome(True, (f"{name or pid} is running with {len(mine)} window(s)." if running
                                    else f"{name or pid} is not running."),
                             data={"running": running, "windows": [w.as_dict() for w in mine],
                                   "active": any(w.active for w in mine)},
                             verified=True, evidence="read from the live window list")

    def dialogs(self, pid: Optional[int] = None) -> list[WindowInfo]:
        return [w for w in self.backend.windows()
                if (pid is None or w.pid == pid) and w.class_name in DIALOG_CLASSES]

    def _dialog_text(self, dialog: WindowInfo) -> tuple[str, list[str]]:
        try:
            els = self.elements(dialog)
        except BackendError:
            return dialog.title, []
        text = " ".join(e.name for e in els if e.control_type == "Text" and e.name)
        buttons = [e.name for e in els if e.control_type == "Button" and e.name]
        return text or dialog.title, buttons

    def close_app(self, ctx: ActionContext, name: str = "", pid: Optional[int] = None,
                  force: bool = False) -> ActionOutcome:
        def run() -> ActionOutcome:
            ctx.check()
            if pid is not None:
                mine = [w for w in self.backend.windows() if w.pid == pid]
                target_pid = pid
            else:
                state = self.window(WindowQuery(title_contains=name)) if name else None
                if state is None:
                    return _fail("Say which app to close.")
                mine = [w for w in self.backend.windows() if w.pid == state.pid]
                target_pid = state.pid
            if force:
                ok = self.backend.terminate(target_pid, force=True)
                gone = self._wait_until(ctx, lambda: not any(w.pid == target_pid
                                                             for w in self.backend.windows()), 5.0)
                return ActionOutcome(bool(ok), f"Force-closed process {target_pid}." if ok else
                                     f"Process {target_pid} could not be stopped.",
                                     verified=bool(gone), evidence="its windows are gone" if gone else "")
            for w in mine:
                if w.class_name not in DIALOG_CLASSES:
                    self.backend.close_window(w.handle)
            return self._after_close(ctx, target_pid, None)
        return self._guard(run)

    def _after_close(self, ctx: ActionContext, pid: int, handle: Optional[int]) -> ActionOutcome:
        def settled():
            wins = self.backend.windows()
            if handle is not None and not any(w.handle == handle for w in wins):
                return "gone"
            if handle is None and not any(w.pid == pid for w in wins):
                return "gone"
            if any(w.pid == pid and w.class_name in DIALOG_CLASSES for w in wins):
                return "dialog"
            return None

        result = self._wait_until(ctx, settled, 5.0)
        if result == "gone":
            return ActionOutcome(True, "Closed.", verified=True, evidence="the window is gone")
        dialogs = self.dialogs(pid)
        if dialogs:
            text, buttons = self._dialog_text(dialogs[0])
            return ActionOutcome(False, f"A dialog is asking: \"{text}\" (buttons: {', '.join(buttons)}). "
                                 "Nothing was answered for you.",
                                 data={"dialog": dialogs[0].as_dict(), "buttons": buttons, "text": text},
                                 verified=False, evidence="blocked by a dialog")
        return ActionOutcome(False, "The window did not close.", verified=False, evidence="still open")

    # ── windows ──────────────────────────────────────────────────────────
    def list_windows(self, ctx: ActionContext, query: WindowQuery | None = None) -> ActionOutcome:
        ctx.check()
        wins = self.windows(query)
        lines = [f"'{w.title}' ({w.process_name or w.pid}{', active' if w.active else ''}"
                 f"{', minimized' if w.minimized else ''})" for w in wins[:20]]
        return ActionOutcome(True, f"{len(wins)} window(s): " + "; ".join(lines) if wins else "No windows match.",
                             data={"windows": [w.as_dict() for w in wins[:_MAX_LIST]]},
                             verified=True, evidence="read from the live window list")

    def activate(self, ctx: ActionContext, query: WindowQuery) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(query)
            ctx.check()
            self.backend.activate(w.handle)
            now = self._wait_until(ctx, lambda: next((x for x in self.backend.windows()
                                                      if x.handle == w.handle and x.active), None), 3.0)
            return ActionOutcome(True, f"Switched to '{w.title}'.", data={"window": w.as_dict()},
                                 verified=bool(now), evidence="it is the foreground window" if now
                                 else "Windows did not bring it to the foreground")
        return self._guard(run)

    def set_state(self, ctx: ActionContext, query: WindowQuery, state: str) -> ActionOutcome:
        state = str(state).lower()
        if state not in ("minimize", "maximize", "restore"):
            return _fail(f"Unknown window state '{state}'.")

        def run() -> ActionOutcome:
            w = self.window(query)
            ctx.check()
            self.backend.set_window_state(w.handle, state)

            def check():
                x = next((x for x in self.backend.windows() if x.handle == w.handle), None)
                if x is None:
                    return None
                return {"minimize": x.minimized, "maximize": x.maximized,
                        "restore": not x.minimized and not x.maximized}[state] and x
            now = self._wait_until(ctx, check, 3.0)
            return ActionOutcome(True, f"{state.title()}d '{w.title}'.",
                                 data={"window": (now or w).as_dict()}, verified=bool(now),
                                 evidence=f"window reports {state}d" if now else "state did not change")
        return self._guard(run)

    def move_resize(self, ctx: ActionContext, query: WindowQuery, left: Optional[int] = None,
                    top: Optional[int] = None, width: Optional[int] = None,
                    height: Optional[int] = None) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(query)
            r = w.rect
            if r is None:
                return _fail(f"'{w.title}' does not report its position.")
            sw, sh = self.backend.screen_size()
            nl = int(left if left is not None else r.left)
            nt = int(top if top is not None else r.top)
            nw = int(width if width is not None else r.width)
            nh = int(height if height is not None else r.height)
            if nw < 100 or nh < 60:
                return _fail("That size is too small to be usable (minimum 100x60).")
            if nl + nw < 50 or nt + 30 < 0 or nl > sw - 50 or nt > sh - 30:
                return _fail(f"That would put the window off the screen ({sw}x{sh}).")
            ctx.check()
            self.backend.move_resize(w.handle, nl, nt, nw, nh)

            def check():
                x = next((x for x in self.backend.windows() if x.handle == w.handle), None)
                if x is None or x.rect is None:
                    return None
                ok = (abs(x.rect.left - nl) <= 8 and abs(x.rect.top - nt) <= 8
                      and abs(x.rect.width - nw) <= 16 and abs(x.rect.height - nh) <= 16)
                return x if ok else None
            now = self._wait_until(ctx, check, 3.0)
            return ActionOutcome(True, f"Moved '{w.title}' to ({nl}, {nt}) size {nw}x{nh}.",
                                 data={"window": (now or w).as_dict()}, verified=bool(now),
                                 evidence="window reports the new geometry" if now else
                                 "the window did not take the requested geometry")
        return self._guard(run)

    def close_window(self, ctx: ActionContext, query: WindowQuery) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(query)
            ctx.check()
            self.backend.close_window(w.handle)
            return self._after_close(ctx, w.pid, w.handle)
        return self._guard(run)

    def inspect_window(self, ctx: ActionContext, query: WindowQuery, depth: int = 6) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(query)
            ctx.check()
            els = self.backend.elements(w.handle, depth=max(1, min(int(depth), 12)))
            interesting = [e for e in els if e.name or e.automation_id][:80]
            return ActionOutcome(True, f"'{w.title}' has {len(els)} controls: " +
                                 "; ".join(e.short() for e in interesting[:25]),
                                 data={"window": w.as_dict(), "elements": [e.as_dict() for e in interesting]},
                                 verified=True, evidence="read through UI Automation")
        return self._guard(run)

    def wait_window(self, ctx: ActionContext, query: WindowQuery, timeout: float = 10.0) -> ActionOutcome:
        found = self._wait_until(ctx, lambda: next(iter(self.windows(query)), None), timeout)
        if found is None:
            return _fail(f"No window matching {query.describe()} appeared within {timeout:.0f}s.")
        return ActionOutcome(True, f"'{found.title}' is open.", data={"window": found.as_dict()},
                             verified=True, evidence="window present")

    # ── controls ─────────────────────────────────────────────────────────
    def find(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            ctx.check()
            if eq.empty():
                els = self.elements(w)
            else:
                els = [e for e in self.elements(w) if eq.matches(e)]
            return ActionOutcome(True, f"{len(els)} control(s) in '{w.title}' match {eq.describe()}" +
                                 (": " + "; ".join(e.short() for e in els[:10]) if els else "."),
                                 data={"window": w.as_dict(), "elements": [e.as_dict() for e in els[:_MAX_LIST]]},
                                 verified=True, evidence="read through UI Automation")
        return self._guard(run)

    def read(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            el = self.element(w, eq)
            if el.is_password:
                return ActionOutcome(True, f"'{el.name}' is a password field; its content is never read.",
                                     data={"element": el.as_dict()}, verified=True)
            value = self.backend.get_value(el.ref)
            shown = value if value is not None else el.name
            return ActionOutcome(True, f"{el.control_type} '{el.name}': {shown!r}",
                                 data={"element": el.as_dict(), "value": value}, verified=True,
                                 evidence="read through UI Automation")
        return self._guard(run)

    def invoke(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery, params: dict | None = None,
               *, method: str = "invoke") -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            el = self.element(w, eq)
            ctx.check()
            (self.backend.click if method == "click" else self.backend.invoke)(el.ref)
            verified, evidence = self._expectation(ctx, w, params or {})
            return ActionOutcome(True, f"{'Clicked' if method == 'click' else 'Pressed'} "
                                 f"{el.control_type} '{el.name}' in '{w.title}'.",
                                 data={"element": el.as_dict()}, verified=verified, evidence=evidence)
        return self._guard(run)

    def set_text(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery, text: str) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            el = self.element(w, eq)
            self._mark_password(ctx, el)
            ctx.check()
            self.backend.set_text(el.ref, str(text))
            if el.is_password:
                return ActionOutcome(True, f"Entered the password into '{el.name}'.",
                                     data={"element": el.as_dict()}, verified=None,
                                     evidence="password fields are never read back")
            value = self.backend.get_value(el.ref)
            ok = value is not None and value.replace("\r\n", "\n") == str(text).replace("\r\n", "\n")
            return ActionOutcome(True, f"Typed {len(str(text))} characters into '{el.name}'.",
                                 data={"element": el.as_dict()}, verified=ok,
                                 evidence="the field reads back the same text" if ok else
                                 f"the field reads back {str(value)[:60]!r}")
        return self._guard(run)

    def select(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery, item: str) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            el = self.element(w, eq)
            ctx.check()
            self.backend.select(el.ref, str(item))
            value = self.backend.get_value(el.ref)
            ok = value is not None and value.casefold() == str(item).casefold()
            return ActionOutcome(True, f"Selected '{item}' in '{el.name}'.", data={"element": el.as_dict()},
                                 verified=ok, evidence=f"value is now {value!r}")
        return self._guard(run)

    def toggle(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            el = self.element(w, eq)
            ctx.check()
            state = self.backend.toggle(el.ref)
            return ActionOutcome(True, f"'{el.name}' is now {state}.", data={"state": state},
                                 verified=state in ("on", "off"), evidence=f"toggle state {state}")
        return self._guard(run)

    def menu(self, ctx: ActionContext, wq: WindowQuery, path: str, params: dict | None = None) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            ctx.check()
            self.backend.menu_select(w.handle, str(path))
            verified, evidence = self._expectation(ctx, w, params or {})
            return ActionOutcome(True, f"Chose {path} in '{w.title}'.", verified=verified, evidence=evidence)
        return self._guard(run)

    def wait_element(self, ctx: ActionContext, wq: WindowQuery, eq: ElementQuery,
                     timeout: float = 10.0) -> ActionOutcome:
        def probe():
            try:
                w = self.window(wq)
                return next((e for e in self.elements(w) if eq.matches(e)), None)
            except BackendError:
                return None
        el = self._wait_until(ctx, probe, timeout)
        if el is None:
            return _fail(f"No control matching {eq.describe()} appeared within {timeout:.0f}s.")
        return ActionOutcome(True, f"{el.short()} is available.", data={"element": el.as_dict()},
                             verified=True, evidence="control present and enabled")

    # ── keyboard (to a named window) ─────────────────────────────────────
    def type_text(self, ctx: ActionContext, wq: WindowQuery, text: str) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            ctx.check()
            text_s = str(text)
            if len(text_s) > 5000:
                return _fail("That is too much text to type at once (5000 characters max).")
            for i in range(0, len(text_s), 500):
                ctx.check()
                self.backend.send_text(w.handle, text_s[i:i + 500])
            return ActionOutcome(True, f"Typed {len(text_s)} characters into '{w.title}'.",
                                 data={"window": w.as_dict()})
        return self._guard(run)

    def hotkey(self, ctx: ActionContext, wq: WindowQuery, keys: list[str]) -> ActionOutcome:
        def run() -> ActionOutcome:
            w = self.window(wq)
            if not keys or len(keys) > 4:
                return _fail("A shortcut needs one to four keys.")
            ctx.check()
            self.backend.send_hotkey(w.handle, [str(k) for k in keys])
            return ActionOutcome(True, f"Pressed {'+'.join(keys)} in '{w.title}'.")
        return self._guard(run)

    # ── coordinate fallback (Project 6) ──────────────────────────────────
    def pointer(self, ctx: ActionContext, op: str, params: dict) -> ActionOutcome:
        fb = self.fallback

        def target(prefix: str = "") -> Target:
            fp = params.get(prefix + "fingerprint")
            return Target(x=params.get(prefix + "x"), y=params.get(prefix + "y"),
                          source=str(params.get("source") or "model"),
                          confidence=float(params.get("confidence", 1.0) or 0.0),
                          fingerprint=int(fp) if fp not in (None, "") else None,
                          label=str(params.get("target") or ""))

        def run() -> ActionOutcome:
            if op == "click":
                return fb.click(ctx, target(), button=str(params.get("button") or "left"))
            if op == "double_click":
                return fb.click(ctx, target(), clicks=2)
            if op == "right_click":
                return fb.click(ctx, target(), button="right")
            if op == "move":
                return fb.move(ctx, params.get("x"), params.get("y"))
            if op == "drag":
                end = Target(params.get("to_x"), params.get("to_y"), source="owner")
                return fb.drag(ctx, target(), end)
            if op == "scroll":
                return fb.scroll(ctx, int(params.get("amount") or -3), params.get("x"), params.get("y"))
            if op == "position":
                x, y = fb.driver.position()
                return ActionOutcome(True, f"Pointer is at ({x}, {y}).", data={"x": x, "y": y}, verified=True)
            if op == "type":
                return fb.type_text(ctx, str(params.get("text") or ""))
            if op == "hotkey":
                keys = params.get("keys")
                keys = keys if isinstance(keys, list) else str(keys or "").replace(" ", "").split("+")
                return fb.hotkey(ctx, keys)
            return _fail(f"Unknown pointer operation '{op}'.")
        return self._guard(run)


_controller: Optional[WindowsController] = None


def get_controller() -> WindowsController:
    global _controller
    if _controller is None:
        _controller = WindowsController()
    return _controller


def set_controller(controller: Optional[WindowsController]) -> None:
    global _controller
    _controller = controller
