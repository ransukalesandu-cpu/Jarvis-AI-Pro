"""Generic laptop control used by the PC tools in actions/ (Module 3).

Nothing here knows about a particular app, site or service. Windows is the
first target (PowerShell, cmd, winget, Explorer); the same functions work on
macOS/Linux where an equivalent exists so tests can run anywhere.

All functions return plain data; the tool wrappers turn it into sentences.
Long or blocking work accepts a ``cancel_event`` so "Jarvis, stop" can end it.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = os.name == "nt"
_OUT_CHARS = 6000
_ERR_CHARS = 3000


# ── run_command ───────────────────────────────────────────────────────────────
@dataclass
class CommandResult:
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    cancelled: bool = False
    duration: float = 0.0
    argv: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.cancelled:
            head = "Command stopped on request."
        elif self.timed_out:
            head = f"Command timed out after {self.duration:.0f}s and was stopped."
        else:
            head = f"Exit code {self.exit_code}."
        parts = [head]
        if self.stdout.strip():
            parts.append("stdout:\n" + self.stdout.strip())
        if self.stderr.strip():
            parts.append("stderr:\n" + self.stderr.strip())
        return "\n".join(parts)


def shell_argv(command: str, shell: str = "powershell") -> list[str]:
    shell = (shell or "powershell").strip().lower()
    if IS_WINDOWS:
        if shell == "cmd":
            return ["cmd", "/d", "/s", "/c", command]
        exe = "pwsh" if shell == "pwsh" else "powershell"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", command]
    if shell in ("powershell", "pwsh") and shutil.which("pwsh"):
        return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-c", command]


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception as exc:   # already gone
            print(f"[pc_control] kill failed: {exc}")


def _tail(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else "…" + text[-limit:]


def run_command(command: str, *, shell: str = "powershell", timeout: float = 60.0,
                cwd: str | None = None, cancel_event: threading.Event | None = None,
                argv: list[str] | None = None) -> CommandResult:
    """Run a shell command; stop it on timeout or when ``cancel_event`` is set."""
    argv = argv or shell_argv(command, shell)
    kwargs: dict = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="replace",
                        cwd=os.path.expandvars(os.path.expanduser(cwd)) if cwd else None)
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except FileNotFoundError as exc:
        return CommandResult(exit_code=None, stderr=f"Could not start {argv[0]}: {exc}", argv=argv)
    out_parts: list[str] = []
    err_parts: list[str] = []

    def pump(stream, sink):
        for line in iter(stream.readline, ""):
            sink.append(line)
        stream.close()

    readers = [threading.Thread(target=pump, args=(proc.stdout, out_parts), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err_parts), daemon=True)]
    for r in readers:
        r.start()
    timed_out = cancelled = False
    deadline = started + max(1.0, float(timeout))
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if time.monotonic() >= deadline:
            timed_out = True
            break
        time.sleep(0.05)
    if timed_out or cancelled:
        _kill_tree(proc)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    for r in readers:
        r.join(timeout=2)
    return CommandResult(
        exit_code=proc.returncode, stdout=_tail("".join(out_parts), _OUT_CHARS),
        stderr=_tail("".join(err_parts), _ERR_CHARS), timed_out=timed_out,
        cancelled=cancelled, duration=time.monotonic() - started, argv=argv,
    )


# ── open ──────────────────────────────────────────────────────────────────────
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]{1,30}:(//)?\S+")


def open_target(target: str = "", app: str = "") -> str:
    """Open any file, folder, URL, launcher URI or app, optionally with a named app."""
    target = os.path.expandvars(os.path.expanduser(str(target or "").strip()))
    app = str(app or "").strip()
    if not target and not app:
        raise ValueError("nothing to open")
    looks_like_url = bool(_URL_RE.match(target)) and not re.match(r"^[a-zA-Z]:\\", target)
    if IS_WINDOWS:
        if app:
            # `start` resolves App Paths names (chrome, winword...) like the Run box.
            args = ["cmd", "/c", "start", "", app] + ([target] if target else [])
            subprocess.Popen(args, close_fds=True)
            return f"Opened {target or app} with {app}."
        try:
            os.startfile(target)   # files, folders, URLs, steam://, ms-settings:, app names
        except OSError:
            subprocess.Popen(["cmd", "/c", "start", "", target], close_fds=True)
        return f"Opened {target}."
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if app:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", app] + ([target] if target else []))
        else:
            subprocess.Popen([app] + ([target] if target else []), start_new_session=True)
        return f"Opened {target or app} with {app}."
    if looks_like_url or Path(target).exists():
        subprocess.Popen([opener, target], start_new_session=True)
    else:
        subprocess.Popen([target], start_new_session=True)
    return f"Opened {target}."


# ── files ─────────────────────────────────────────────────────────────────────
def _p(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path or "").strip() or "~")))


def search_roots() -> list[Path]:
    """Every fixed drive on Windows, otherwise the home folder."""
    if IS_WINDOWS:
        roots = []
        try:
            import psutil
            for part in psutil.disk_partitions(all=False):
                if "cdrom" not in (part.opts or "") and part.fstype:
                    roots.append(Path(part.mountpoint))
        except Exception:
            roots = [Path(os.environ.get("SystemDrive", "C:") + "\\")]
        return roots
    return [Path.home()]


_SKIP_DIRS = {"$recycle.bin", "system volume information", "windows", "winsxs",
              "node_modules", ".git", "__pycache__", "appdata"}


def search_files(pattern: str, root: str = "", *, contains: str = "", max_results: int = 20,
                 time_budget: float = 20.0, cancel_event: threading.Event | None = None) -> list[str]:
    """Find files whose name matches ``pattern`` (glob or substring) under root(s)."""
    pattern = str(pattern or "").strip()
    if not pattern and not contains:
        raise ValueError("give a file name pattern or text to look for")
    glob = (pattern if any(c in pattern for c in "*?[") else f"*{pattern}*") if pattern else "*"
    where = str(root or "").strip()
    if where.lower() in ("all", "everywhere", "all drives"):
        roots = search_roots()
    elif where:
        roots = [_p(where)]
    else:
        roots = [Path.home()]
    deadline = time.monotonic() + time_budget
    needle = contains.lower()
    found: list[str] = []
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda _e: None):
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS]
            for name in filenames:
                if not fnmatch.fnmatch(name.lower(), glob.lower()):
                    continue
                full = os.path.join(dirpath, name)
                if needle:
                    try:
                        with open(full, encoding="utf-8", errors="ignore") as fh:
                            if needle not in fh.read(2_000_000).lower():
                                continue
                    except OSError:
                        continue
                found.append(full)
                if len(found) >= max_results:
                    return found
            if time.monotonic() > deadline or (cancel_event and cancel_event.is_set()):
                return found
    return found


def read_file(path: str, max_chars: int = 8000) -> str:
    p = _p(path)
    data = p.read_bytes()[: max_chars * 4]
    if b"\x00" in data[:4096]:
        return f"{p} is a binary file ({p.stat().st_size} bytes)."
    text = data.decode("utf-8", errors="replace")
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def write_file(path: str, content: str, append: bool = False) -> str:
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a" if append else "w", encoding="utf-8") as fh:
        fh.write(content or "")
    return f"{'Appended to' if append else 'Wrote'} {p} ({len(content or '')} characters)."


def move_path(src: str, dst: str) -> str:
    s, d = _p(src), _p(dst)
    if d.is_dir():
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"Moved {s} to {d}."


def copy_path(src: str, dst: str) -> str:
    s, d = _p(src), _p(dst)
    if d.is_dir():
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return f"Copied {s} to {d}."


def delete_path(path: str) -> str:
    p = _p(path)
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()
    return f"Deleted {p}."


def list_dir(path: str, max_entries: int = 50) -> list[str]:
    p = _p(path)
    rows = []
    for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:max_entries]:
        try:
            size = "" if entry.is_dir() else f" ({entry.stat().st_size:,} bytes)"
        except OSError:
            size = ""
        rows.append(f"{entry.name}{'/' if entry.is_dir() else ''}{size}")
    return rows


# ── system info ───────────────────────────────────────────────────────────────
def drives() -> list[dict]:
    import psutil
    out = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in (part.opts or "") or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        out.append({"drive": part.mountpoint, "free_gb": round(usage.free / 1e9, 1),
                    "total_gb": round(usage.total / 1e9, 1), "fstype": part.fstype})
    return sorted(out, key=lambda d: d["free_gb"], reverse=True)


def best_drive(min_free_gb: float = 0.0) -> dict | None:
    """The drive with the most free space (and at least ``min_free_gb``)."""
    for d in drives():
        if d["free_gb"] >= min_free_gb:
            return d
    return None


def memory() -> dict:
    import psutil
    vm = psutil.virtual_memory()
    return {"total_gb": round(vm.total / 1e9, 1), "available_gb": round(vm.available / 1e9, 1),
            "used_percent": vm.percent}


def processes(top: int = 10, sort: str = "memory") -> list[dict]:
    import psutil
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
        info = proc.info
        mem = info.get("memory_info")
        rows.append({"pid": info["pid"], "name": info.get("name") or "?",
                     "memory_mb": round(mem.rss / 1e6) if mem else 0,
                     "cpu_percent": info.get("cpu_percent") or 0.0})
    key = "cpu_percent" if sort == "cpu" else "memory_mb"
    return sorted(rows, key=lambda r: r[key], reverse=True)[:max(1, int(top))]


def battery() -> dict | None:
    import psutil
    try:
        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None:
        return None
    return {"percent": round(b.percent), "plugged_in": bool(b.power_plugged),
            "minutes_left": None if b.secsleft in (psutil.POWER_TIME_UNLIMITED,
                                                     psutil.POWER_TIME_UNKNOWN)
            else int(b.secsleft // 60)}


# ── winget ────────────────────────────────────────────────────────────────────
_WINGET_COMMON = ["--accept-source-agreements", "--disable-interactivity"]
_WINGET_ID_RE = re.compile(r"^[A-Za-z0-9][\w.+-]*\.[\w.+-]+$")


def _winget_target(package: str) -> list[str]:
    package = str(package or "").strip()
    if not package:
        raise ValueError("which package?")
    # Publisher.App identifiers match exactly; anything else is a name query.
    return ["--id", package, "-e"] if _WINGET_ID_RE.match(package) else ["--name", package]


def install_location(package: str, location: str = "") -> str:
    """'' = installer default; 'auto' = the drive with the most free space."""
    loc = str(location or "").strip()
    if loc.lower() != "auto":
        return loc
    d = best_drive()
    if d is None:
        return ""
    system = (os.environ.get("SystemDrive", "C:") + "\\").upper()
    if d["drive"].upper() == system:
        return ""     # default Program Files is already on the roomiest drive
    safe = re.sub(r"[^\w.-]+", "_", package)
    return str(Path(d["drive"]) / "Programs" / safe)


def winget_argv(action: str, package: str = "", *, location: str = "",
                query: str = "") -> list[str]:
    action = str(action or "").strip().lower()
    if action == "install":
        argv = ["winget", "install", *_winget_target(package), "--silent",
                "--accept-package-agreements", *_WINGET_COMMON]
        loc = install_location(package, location)
        if loc:
            argv += ["--location", loc]
        return argv
    if action == "upgrade":
        if not package or package.lower() in ("all", "everything"):
            return ["winget", "upgrade", "--all", "--include-unknown", "--silent",
                    "--accept-package-agreements", *_WINGET_COMMON]
        return ["winget", "upgrade", *_winget_target(package), "--silent",
                "--accept-package-agreements", *_WINGET_COMMON]
    if action == "uninstall":
        return ["winget", "uninstall", *_winget_target(package), "--silent", *_WINGET_COMMON]
    if action == "list":
        return ["winget", "list", *(["--query", query or package] if (query or package) else []),
                *_WINGET_COMMON]
    if action == "search":
        return ["winget", "search", query or package, *_WINGET_COMMON]
    if action == "outdated":
        return ["winget", "upgrade", "--include-unknown", *_WINGET_COMMON]
    raise ValueError("action must be install, upgrade, uninstall, list, search or outdated")
