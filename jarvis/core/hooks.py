"""Lifecycle hooks: run owner code when something happens in JARVIS.

Events: startup, shutdown, session_start, session_end, trigger_fired,
trigger_failed, task_finished, tool_error, privacy_lock.

Two kinds of hook, both fire on :func:`emit`:

* **Python hooks** — an ``actions/*.py`` or plugin module exposes
  ``HOOKS = [{"event": "task_finished", "handler": fn, "name": "..."}]``;
  ``fn(event, payload)`` runs in the hook worker thread with a 5 s limit.
* **Script hooks** — files the *owner* puts in ``<user data>/hooks/<event>/``
  (``.py``, ``.ps1``, ``.bat``, ``.cmd``, ``.sh``). Each runs as a separate
  process with the JSON payload on stdin.

Guard rails for script hooks: only that user-data folder is scanned (never the
repository, downloads, or paths from chat/web/tool output) and JARVIS never writes
into it; files are run by a fixed interpreter without a shell; 30 s timeout;
output capped at 64 KB; minimal environment (no API keys); symlinks and files that
resolve outside the folder are ignored; every run is written to the security
ledger; three failures in a row switch a hook off. Set ``JARVIS_DISABLE_HOOKS=1``
to turn all hooks off.

``emit`` never blocks the caller and never raises: work goes to one background
worker (bounded queue, oldest events are dropped when it is full). The event is
also forwarded to :mod:`jarvis.core.events` so owner rules can match it.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.core import failsoft

EVENTS = ("startup", "shutdown", "session_start", "session_end", "trigger_fired",
          "trigger_failed", "task_finished", "tool_error", "privacy_lock")
PY_TIMEOUT = 5.0
SCRIPT_TIMEOUT = 30.0
OUTPUT_LIMIT = 64 * 1024
QUEUE_LIMIT = 100
MAX_FAILURES = 3
_SCRIPT_RUNNERS = {".py": "python", ".ps1": "powershell", ".bat": "cmd", ".cmd": "cmd", ".sh": "bash"}
_ENV_KEEP = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
             "HOME", "USERPROFILE", "LANG", "LC_ALL")


def hooks_dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "hooks"


def _disabled() -> bool:
    return os.environ.get("JARVIS_DISABLE_HOOKS", "").strip().lower() in ("1", "true", "yes")


def _command_for(path: Path) -> Optional[list[str]]:
    kind = _SCRIPT_RUNNERS.get(path.suffix.lower())
    if kind == "python":
        return [sys.executable, "-I", str(path)]
    if kind == "powershell":
        exe = shutil.which("powershell") or shutil.which("pwsh")
        return [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)] if exe else None
    if kind == "cmd":
        return ["cmd", "/c", str(path)] if os.name == "nt" else None
    if kind == "bash":
        exe = shutil.which("bash")
        return [exe, str(path)] if exe else None
    return None


def _clean_env(event: str) -> dict[str, str]:
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env["JARVIS_HOOK_EVENT"] = event
    return env


class HookRegistry:
    def __init__(self, directory: Optional[Path] = None):
        self._dir = directory
        self._lock = threading.RLock()
        self._python: list[dict] = []
        self._failures: dict[str, int] = {}
        self._off: set[str] = set()
        self._queue: "queue.Queue[Optional[tuple[str, dict]]]" = queue.Queue(maxsize=QUEUE_LIMIT)
        self._worker: Optional[threading.Thread] = None
        self._idle = threading.Event()
        self._idle.set()
        self.notify: Optional[Callable[[str], None]] = None     # told when a hook is switched off
        self.audit: Optional[Callable[[str, str], None]] = None  # (hook name, detail)

    # ── python hooks ─────────────────────────────────────────────────────────
    def register(self, event: str, handler: Callable[[str, dict], Any], name: str = "") -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown hook event '{event}'")
        if not callable(handler):
            raise ValueError("hook handler must be callable")
        with self._lock:
            label = name or getattr(handler, "__name__", "hook")
            self._python = [h for h in self._python if not (h["event"] == event and h["name"] == label)]
            self._python.append({"event": event, "handler": handler, "name": label})

    def python_hooks(self, event: str) -> list[dict]:
        with self._lock:
            return [h for h in self._python if h["event"] == event]

    # ── script discovery ─────────────────────────────────────────────────────
    def script_hooks(self, event: str) -> list[Path]:
        root = (self._dir if self._dir is not None else hooks_dir()) / event
        try:
            if not root.is_dir() or root.is_symlink():
                return []
            real_root = root.resolve()
            found = []
            for path in sorted(root.iterdir()):
                if path.name.startswith((".", "_")) or path.is_symlink() or not path.is_file():
                    continue
                if path.suffix.lower() not in _SCRIPT_RUNNERS:
                    continue
                if real_root not in path.resolve().parents:
                    continue
                found.append(path)
            return found
        except OSError:
            return []

    # ── emitting ─────────────────────────────────────────────────────────────
    def emit(self, event: str, payload: Optional[dict] = None, *, wait: float = 0.0) -> None:
        """Queue an event. With ``wait`` > 0, block up to that many seconds for the queue to drain."""
        if event not in EVENTS:
            return
        payload = dict(payload or {})
        try:
            from jarvis.core import events
            events.emit(event, payload)
        except Exception as exc:
            print(f"[Hooks] event bus failed: {type(exc).__name__}: {exc}")
        if _disabled():
            return
        if not self.python_hooks(event) and not self.script_hooks(event):
            return
        self._ensure_worker()
        self._idle.clear()
        try:
            self._queue.put_nowait((event, payload))
        except queue.Full:
            try:
                self._queue.get_nowait()          # drop the oldest
                self._queue.put_nowait((event, payload))
            except (queue.Empty, queue.Full):
                pass
        if wait > 0:
            self._idle.wait(wait)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, name="jarvis-hooks", daemon=True)
                self._worker.start()

    def _loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=2.0)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._worker = None
                        self._idle.set()
                        return
                continue
            if item is None:
                return
            event, payload = item
            try:
                self.run_event(event, payload)
            except Exception as exc:        # nothing may kill the worker
                print(f"[Hooks] {event} failed: {type(exc).__name__}: {exc}")
            if self._queue.empty():
                self._idle.set()

    # ── running ──────────────────────────────────────────────────────────────
    def run_event(self, event: str, payload: dict) -> list[tuple[str, bool, str]]:
        """Run every hook for ``event`` now (worker thread / tests). Returns (name, ok, detail)."""
        results = []
        for hook in self.python_hooks(event):
            results.append(self._run_python(hook, event, payload))
        for path in self.script_hooks(event):
            results.append(self._run_script(path, event, payload))
        return results

    def _record(self, key: str, ok: bool, detail: str) -> None:
        with self._lock:
            if ok:
                self._failures[key] = 0
                return
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] >= MAX_FAILURES:
                self._off.add(key)
                message = f"Hook '{key}' failed {MAX_FAILURES} times in a row and was switched off. {detail[:200]}"
            else:
                return
        print(f"[Hooks] {message}")
        if self.notify:
            try:
                self.notify(message)
            except Exception:
                failsoft.suppress("hooks:notify")

    def _audit(self, key: str, detail: str) -> None:
        if self.audit:
            try:
                self.audit(key, detail)
            except Exception:
                failsoft.suppress("hooks:audit")

    def is_off(self, key: str) -> bool:
        return key in self._off

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._off.clear()
                self._failures.clear()
            else:
                self._off.discard(key)
                self._failures.pop(key, None)

    def _run_python(self, hook: dict, event: str, payload: dict) -> tuple[str, bool, str]:
        key = f"py:{hook['name']}"
        if key in self._off:
            return key, False, "switched off"
        box: dict = {}

        def call():
            try:
                hook["handler"](event, dict(payload))
                box["ok"] = True
            except Exception as exc:
                box["error"] = f"{type(exc).__name__}: {exc}"

        thread = threading.Thread(target=call, name=f"hook-{hook['name']}", daemon=True)
        thread.start()
        thread.join(PY_TIMEOUT)
        if thread.is_alive():
            ok, detail = False, f"timed out after {PY_TIMEOUT:g}s"
        else:
            ok, detail = bool(box.get("ok")), box.get("error", "")
        self._record(key, ok, detail)
        self._audit(key, f"{event}: {'ok' if ok else detail}")
        return key, ok, detail

    def _run_script(self, path: Path, event: str, payload: dict) -> tuple[str, bool, str]:
        key = f"script:{event}/{path.name}"
        if key in self._off:
            return key, False, "switched off"
        command = _command_for(path)
        if command is None:
            return key, False, "no interpreter for this file type on this system"
        body = json.dumps({"event": event, "payload": payload, "at": time.time()}, default=str)
        try:
            proc = subprocess.run(command, input=body, capture_output=True, text=True,
                                  timeout=SCRIPT_TIMEOUT, cwd=str(path.parent),
                                  env=_clean_env(event), shell=False)
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-OUTPUT_LIMIT:].strip()
            ok = proc.returncode == 0
            detail = "" if ok else f"exit {proc.returncode}: {tail[-200:]}"
        except subprocess.TimeoutExpired:
            ok, detail = False, f"timed out after {SCRIPT_TIMEOUT:g}s"
        except OSError as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self._record(key, ok, detail)
        self._audit(key, f"{event}: {'ok' if ok else detail}")
        return key, ok, detail


_REGISTRY: Optional[HookRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_hook_registry() -> HookRegistry:
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            reg = HookRegistry()
            reg.audit = _ledger
            _REGISTRY = reg
        return _REGISTRY


def _ledger(key: str, detail: str) -> None:
    from jarvis.core import security
    security.audit("hook", key, "SENSITIVE", "ran", detail)


def emit(event: str, payload: Optional[dict] = None, *, wait: float = 0.0) -> None:
    """Report a lifecycle event. Never raises, never blocks (except the optional ``wait``)."""
    try:
        get_hook_registry().emit(event, payload, wait=wait)
    except Exception as exc:
        print(f"[Hooks] emit({event}) failed: {type(exc).__name__}: {exc}")


def reset_for_tests(registry: Optional[HookRegistry] = None) -> None:
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = registry
