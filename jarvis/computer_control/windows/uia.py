"""The real Windows backend: pywinauto UI Automation + Win32 for window geometry.

pywinauto (BSD-3, already a declared ``sys_platform == "win32"`` dependency) is
imported lazily, on Windows only. Ideas taken from pywinauto's own design: the
UIA backend for controls (names, automation ids, control types, patterns such as
Invoke/Value/Toggle/Selection), the Win32 ``HwndWrapper`` for reliable window
state and geometry, ``menu_select("File->Save")`` paths, and ``send_keys``
syntax for keyboard input.

Rules kept here:

* accessibility patterns first (``invoke``, ``set_edit_text``, ``select``,
  ``toggle``); ``click_input`` (which moves the real mouse) only when the
  control exposes no pattern;
* password fields (UIA ``IsPassword``) are flagged and their value is never read;
* every COM call runs after a per-thread ``CoInitialize`` (the runner's worker
  threads are not the importing thread);
* nothing outside the referenced window/process is touched.
"""
from __future__ import annotations

import os
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from jarvis.core import failsoft
from jarvis.computer_control.windows.backend import BackendError, BackendUnavailable, ElementGone
from jarvis.computer_control.windows.model import AppInfo, ElementInfo, ProcessInfo, Rect, WindowInfo

_tls = threading.local()
_MAX_CACHED = 4000

_KEY_NAMES = {
    "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "space": "{SPACE}", "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}",
    "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pagedown": "{PGDN}", "up": "{UP}",
    "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}", "insert": "{INSERT}",
    **{f"f{i}": f"{{F{i}}}" for i in range(1, 13)},
}
_MODIFIERS = {"ctrl": "VK_CONTROL", "control": "VK_CONTROL", "alt": "VK_MENU", "shift": "VK_SHIFT",
              "win": "VK_LWIN", "windows": "VK_LWIN"}


def _co_init() -> None:
    if getattr(_tls, "com", False):
        return
    try:
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
    except OSError:
        pass                       # already initialised in another mode: usable
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("computer_control.windows.uia:co_init")
    _tls.com = True


def escape_send_keys(text: str) -> str:
    """Make literal text safe for pywinauto.keyboard.send_keys."""
    out = []
    for ch in str(text):
        if ch in "{}+^%~()[]":
            out.append("{" + ch + "}")
        elif ch == "\n":
            out.append("{ENTER}")
        elif ch == "\t":
            out.append("{TAB}")
        else:
            out.append(ch)
    return "".join(out)


def hotkey_to_send_keys(keys: list[str]) -> str:
    mods = [k.strip().lower() for k in keys[:-1]]
    last = str(keys[-1]).strip() if keys else ""
    down = "".join(f"{{{_MODIFIERS[m]} down}}" for m in mods if m in _MODIFIERS)
    up = "".join(f"{{{_MODIFIERS[m]} up}}" for m in reversed(mods) if m in _MODIFIERS)
    unknown = [m for m in mods if m not in _MODIFIERS]
    if unknown:
        raise BackendError(f"unknown modifier key(s): {', '.join(unknown)}")
    key = _KEY_NAMES.get(last.lower(), escape_send_keys(last.lower() if len(last) == 1 else last))
    return down + key + up


def menu_label(raw: str) -> str:
    """'&Save\tCtrl+S' -> 'save' (mnemonic and accelerator removed)."""
    return " ".join(str(raw).split("\t", 1)[0].replace("&", "").split()).casefold().rstrip(".…")


def split_menu_path(path: str) -> list[str]:
    import re as _re
    return [p for p in (x.strip() for x in _re.split(r"\s*-?>\s*", str(path))) if p]


def win32_menu_command(hwnd: int, path: str) -> bool:
    """Post the WM_COMMAND of a classic menu item. False when the window has no Win32 menu."""
    import ctypes

    user32 = ctypes.windll.user32
    menu = user32.GetMenu(hwnd)
    if not menu:
        return False
    parts = split_menu_path(path)
    if not parts:
        raise BackendError("empty menu path")
    buf = ctypes.create_unicode_buffer(256)
    for depth, part in enumerate(parts):
        want = menu_label(part)
        count = user32.GetMenuItemCount(menu)
        found = None
        for i in range(max(0, count)):
            user32.GetMenuStringW(menu, i, buf, 255, 0x0400)       # MF_BYPOSITION
            if menu_label(buf.value) == want:
                found = i
                break
        if found is None:
            raise BackendError(f"'{part}' is not in the menu")
        if depth == len(parts) - 1:
            item_id = user32.GetMenuItemID(menu, found)
            if item_id in (0, 0xFFFFFFFF, -1):
                raise BackendError(f"'{part}' opens a submenu; name an item inside it")
            state = user32.GetMenuState(menu, found, 0x0400)
            if state & 0x0003:                                     # MF_GRAYED | MF_DISABLED
                raise BackendError(f"'{part}' is disabled right now")
            if not user32.PostMessageW(hwnd, 0x0111, item_id, 0):  # WM_COMMAND
                raise BackendError("the window did not accept the menu command")
            return True
        menu = user32.GetSubMenu(menu, found)
        if not menu:
            raise BackendError(f"'{part}' has no submenu")
    return False


def _rect(wrapper) -> Optional[Rect]:
    try:
        r = wrapper.rectangle()
        return Rect(int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return None


class PywinautoBackend:
    name = "pywinauto-uia"

    def __init__(self) -> None:
        self._refs: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.RLock()

    # ── availability ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Windows native control only works on Windows."
        try:
            _co_init()
            import pywinauto  # noqa: F401
        except Exception as exc:
            return False, ("Windows UI Automation needs the 'pywinauto' package "
                           f"({type(exc).__name__}: {exc}).")
        return True, ""

    def _pw(self):
        _co_init()
        try:
            import pywinauto
            import pywinauto.keyboard  # noqa: F401 - used as pywinauto.keyboard
            from pywinauto import Desktop
            from pywinauto.controls.hwndwrapper import HwndWrapper
        except Exception as exc:
            raise BackendUnavailable(f"pywinauto is not importable: {exc}") from exc
        return pywinauto, Desktop, HwndWrapper

    # ── discovery ────────────────────────────────────────────────────────
    def installed_apps(self) -> list[AppInfo]:
        apps: dict[str, AppInfo] = {}
        roots = []
        for var in ("PROGRAMDATA", "APPDATA"):
            base = os.environ.get(var)
            if base:
                roots.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        for root in roots:
            try:
                for count, lnk in enumerate(root.rglob("*.lnk")):
                    if count > 2000:
                        break
                    name = lnk.stem
                    if "uninstall" in name.lower():
                        continue
                    apps.setdefault(name.casefold(), AppInfo(name, str(lnk), "start_menu"))
            except OSError:
                continue
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    key = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths")
                except OSError:
                    continue
                with key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub) as sk:
                                target = str(winreg.QueryValue(sk, None) or "").strip('"')
                        except OSError:
                            continue
                        if target:
                            name = sub.removesuffix(".exe").removesuffix(".EXE")
                            apps.setdefault(name.casefold(), AppInfo(name, target, "app_paths"))
        except ImportError:
            pass
        return sorted(apps.values(), key=lambda a: a.name.casefold())

    def processes(self) -> list[ProcessInfo]:
        import psutil
        out = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            info = proc.info
            out.append(ProcessInfo(int(info["pid"]), str(info.get("name") or ""), str(info.get("exe") or "")))
        return out

    def screen_size(self) -> tuple[int, int]:
        import ctypes
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))

    # ── launch / close ───────────────────────────────────────────────────
    def launch(self, target: str, args: list[str]) -> int:
        target = str(target)
        if target.lower().endswith((".lnk", ".url")) or target.endswith(":") or "://" in target:
            os.startfile(target)  # noqa: S606 - a Start-menu shortcut / protocol chosen by the owner
            return 0
        try:
            proc = subprocess.Popen([target, *[str(a) for a in args]], close_fds=True)  # noqa: S603
        except FileNotFoundError as exc:
            raise BackendError(f"'{target}' was not found") from exc
        except OSError as exc:
            raise BackendError(f"could not start '{target}': {exc}") from exc
        return int(proc.pid)

    def terminate(self, pid: int, force: bool = False) -> bool:
        import psutil
        try:
            proc = psutil.Process(int(pid))
            proc.kill() if force else proc.terminate()
            proc.wait(5)
            return True
        except psutil.NoSuchProcess:
            return False
        except psutil.TimeoutExpired:
            return False

    # ── windows ──────────────────────────────────────────────────────────
    def _foreground(self) -> int:
        import ctypes
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)

    def _process_names(self) -> dict[int, str]:
        try:
            import psutil
            return {p.info["pid"]: str(p.info.get("name") or "")
                    for p in psutil.process_iter(["pid", "name"])}
        except Exception:
            return {}

    def windows(self) -> list[WindowInfo]:
        _pw, Desktop, HwndWrapper = self._pw()
        fg = self._foreground()
        names = self._process_names()
        out = []
        for w in Desktop(backend="uia").windows():
            try:
                handle = int(w.handle or 0)
                if not handle:
                    continue
                hw = HwndWrapper(handle)
                pid = int(w.process_id())
                out.append(WindowInfo(
                    handle=handle, title=str(w.window_text() or ""), pid=pid,
                    process_name=names.get(pid, ""), class_name=str(w.element_info.class_name or ""),
                    rect=_rect(w), visible=bool(w.is_visible()), enabled=bool(w.is_enabled()),
                    minimized=bool(hw.is_minimized()), maximized=bool(hw.is_maximized()),
                    active=handle == fg))
            except Exception:
                failsoft.suppress("computer_control.windows.uia:windows")
        return out

    def _hwnd(self, handle: int):
        _pw, _Desktop, HwndWrapper = self._pw()
        try:
            return HwndWrapper(int(handle))
        except Exception as exc:
            raise ElementGone(f"window {handle} no longer exists") from exc

    def _uia_window(self, handle: int):
        _pw, Desktop, _H = self._pw()
        try:
            return Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
        except Exception as exc:
            raise ElementGone(f"window {handle} no longer exists") from exc

    def activate(self, handle: int) -> None:
        """Bring a window to the foreground without touching the mouse.

        pywinauto's ``HwndWrapper.set_focus()`` moves the cursor off-screen first,
        which fails on a non-interactive desktop and moves the owner's pointer on a
        real one. This uses the Win32 calls directly: restore if minimised, then
        ``SetForegroundWindow`` with the input of the current foreground thread
        attached (the documented way to be allowed to take the foreground).
        """
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = wintypes.HWND(int(handle))
        if not user32.IsWindow(hwnd):
            raise ElementGone(f"window {handle} no longer exists")
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
        foreground = user32.GetForegroundWindow()
        if foreground == int(handle):
            return
        this_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = bool(fg_thread) and fg_thread != this_thread and \
            bool(user32.AttachThreadInput(this_thread, fg_thread, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(this_thread, fg_thread, False)

    def set_window_state(self, handle: int, state: str) -> None:
        hw = self._hwnd(handle)
        actions = {"minimize": hw.minimize, "maximize": hw.maximize, "restore": hw.restore}
        if state not in actions:
            raise BackendError(f"unknown window state {state!r}")
        actions[state]()

    def move_resize(self, handle: int, left: int, top: int, width: int, height: int) -> None:
        hw = self._hwnd(handle)
        if hw.is_maximized() or hw.is_minimized():
            hw.restore()
        hw.move_window(int(left), int(top), int(width), int(height), repaint=True)

    def close_window(self, handle: int) -> None:
        self._hwnd(handle).close()

    # ── elements ─────────────────────────────────────────────────────────
    def _remember(self, ref: str, wrapper) -> None:
        with self._lock:
            self._refs[ref] = wrapper
            self._refs.move_to_end(ref)
            while len(self._refs) > _MAX_CACHED:
                self._refs.popitem(last=False)

    def _lookup(self, ref: str):
        with self._lock:
            wrapper = self._refs.get(ref)
        if wrapper is None:
            raise ElementGone(f"control {ref} is not known any more; look it up again")
        try:
            _ = wrapper.element_info.rectangle      # raises once the element is gone
        except Exception as exc:
            raise ElementGone(f"control {ref} no longer exists") from exc
        return wrapper

    @staticmethod
    def _is_password(wrapper) -> bool:
        try:
            return bool(wrapper.element_info.element.CurrentIsPassword)
        except Exception:
            return False

    def _value(self, wrapper, control_type: str) -> Optional[str]:
        if control_type not in ("Edit", "Document", "ComboBox", "Text"):
            return None
        for getter in ("get_value", "window_text"):
            fn = getattr(wrapper, getter, None)
            if callable(fn):
                try:
                    value = fn()
                    if value is not None:
                        return str(value)[:4000]
                except Exception:
                    failsoft.suppress("computer_control.windows.uia:value")
                    continue
        return None

    def elements(self, handle: int, depth: int = 6, limit: int = 400) -> list[ElementInfo]:
        window = self._uia_window(handle)
        try:
            controls = window.descendants(depth=int(depth))
        except TypeError:
            controls = window.descendants()
        out = []
        for i, c in enumerate(controls[: int(limit)]):
            try:
                info = c.element_info
                runtime = "-".join(str(x) for x in (getattr(info, "runtime_id", None) or ())) or f"i{i}"
                ref = f"{int(handle)}:{runtime}"
                control_type = str(info.control_type or "")
                password = self._is_password(c)
                self._remember(ref, c)
                out.append(ElementInfo(
                    ref=ref, name=str(info.name or ""), control_type=control_type,
                    automation_id=str(info.automation_id or ""), class_name=str(info.class_name or ""),
                    rect=_rect(c), enabled=bool(c.is_enabled()), visible=bool(info.visible),
                    is_password=password,
                    value=None if password else self._value(c, control_type),
                    window_handle=int(handle)))
            except Exception:
                failsoft.suppress("computer_control.windows.uia:elements")
                continue
        return out

    def _check_enabled(self, wrapper, ref: str) -> None:
        try:
            enabled = wrapper.is_enabled()
        except Exception as exc:
            raise ElementGone(f"control {ref} no longer exists") from exc
        if not enabled:
            raise BackendError(f"control {ref} is disabled")

    def invoke(self, ref: str) -> None:
        wrapper = self._lookup(ref)
        self._check_enabled(wrapper, ref)
        try:
            wrapper.invoke()
        except Exception as exc:
            raise BackendError(f"control {ref} cannot be invoked: {exc}") from exc

    def click(self, ref: str) -> None:
        wrapper = self._lookup(ref)
        self._check_enabled(wrapper, ref)
        try:
            wrapper.invoke()
            return
        except Exception:
            failsoft.suppress("computer_control.windows.uia:click-invoke")
        wrapper.click_input()      # last resort: the real mouse, on the control's own rectangle

    def set_text(self, ref: str, text: str) -> None:
        wrapper = self._lookup(ref)
        self._check_enabled(wrapper, ref)
        try:
            wrapper.set_edit_text(str(text))
            return
        except Exception:
            failsoft.suppress("computer_control.windows.uia:set_edit_text")
        try:
            wrapper.set_focus()
            wrapper.type_keys("^a{BACKSPACE}" + escape_send_keys(str(text)), with_spaces=True,
                              with_tabs=True, with_newlines=True, pause=0.0)
        except Exception as exc:
            raise BackendError(f"could not type into control {ref}: {exc}") from exc

    def get_value(self, ref: str) -> Optional[str]:
        wrapper = self._lookup(ref)
        if self._is_password(wrapper):
            return None
        return self._value(wrapper, str(wrapper.element_info.control_type or ""))

    def select(self, ref: str, item: str) -> None:
        wrapper = self._lookup(ref)
        self._check_enabled(wrapper, ref)
        try:
            wrapper.select(str(item))
        except Exception as exc:
            raise BackendError(f"could not select '{item}': {exc}") from exc

    def toggle(self, ref: str) -> str:
        wrapper = self._lookup(ref)
        self._check_enabled(wrapper, ref)
        wrapper.toggle()
        try:
            return "on" if int(wrapper.get_toggle_state()) == 1 else "off"
        except Exception:
            return "unknown"

    def menu_select(self, handle: int, path: str) -> None:
        """Choose a menu item without simulated input where possible.

        Classic Win32 menus are walked with the Win32 menu API and the item's
        WM_COMMAND is posted to the window (no mouse, no keyboard, no focus change;
        pywinauto's own menu_select focuses the window by moving the cursor, which
        fails on a non-interactive desktop). Otherwise UI Automation expand/invoke.
        """
        errors = []
        try:
            if win32_menu_command(int(handle), str(path)):
                return
            errors.append("win32: no classic menu")
        except BackendError as exc:
            errors.append(f"win32: {exc}")
        try:
            self._uia_window(handle).menu_select(str(path))
            return
        except Exception as exc:
            errors.append(f"uia: {str(exc)[:80]}")
        raise BackendError(f"menu item '{path}' was not found ({'; '.join(errors)})")

    def send_text(self, handle: int, text: str) -> None:
        pywinauto, _D, _H = self._pw()
        self.activate(handle)
        pywinauto.keyboard.send_keys(escape_send_keys(text), with_spaces=True, with_tabs=True,
                                     with_newlines=True, pause=0.0)

    def send_hotkey(self, handle: int, keys: list[str]) -> None:
        pywinauto, _D, _H = self._pw()
        self.activate(handle)
        pywinauto.keyboard.send_keys(hotkey_to_send_keys(list(keys)), pause=0.0)
