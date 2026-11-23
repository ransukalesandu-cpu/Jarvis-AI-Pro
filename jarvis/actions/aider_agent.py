"""
aider_agent — let JARVIS edit the owner's existing local projects with Aider.

Where this fits next to the other coding tools:
    dev_agent    builds a NEW project from scratch in Desktop/JarvisProjects.
    code_helper  writes or fixes ONE file.
    aider_agent  edits an EXISTING multi-file project (any folder, git repo),
                 using Aider's repo map so it understands the whole codebase.

How it runs
    Aider (github.com/Aider-AI/aider, Apache-2.0) is NOT imported. Its Python
    API is unsupported and its dependency tree would clash with JARVIS, so it is
    installed on its own (``python -m pip install aider-install`` then
    ``aider-install``) and driven through its stable CLI:
        aider --message "<task>" --yes-always --model anthropic/<claude model> ...
    The brain is Claude (the Anthropic key already in JARVIS settings);
    ``JARVIS_AIDER_MODEL`` overrides the model.

Safety rails (they hold in Full Access too; none needs the model's help)
    * The project folder may be anywhere EXCEPT core/path_guard's protected
      locations (JARVIS's own install folder, credentials, autostart folders).
    * Work happens in git. On main/master a branch ``jarvis/aider-<time>`` is
      created first, so the owner's main branch is never committed to. Nothing
      is ever pushed.
    * Aider's shell-command suggestions, auto-lint/auto-test commands, URL
      scraping and Playwright are switched off on the command line, which wins
      over a project's own .aider.conf.yml — a cloned repo cannot make JARVIS
      run commands.
    * The child gets the Anthropic key and nothing else that looks like a
      credential. Aider analytics and update checks are off (NETWORK.md).
    * "stop" / job cancel kills the Aider process tree; a hard timeout too.
    * ``undo`` only reverts commits this tool made (git revert, history kept).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from jarvis.core import path_guard
from jarvis.core.provider_settings import claude_model, get_provider_api_key
from jarvis.core.user_data import user_data_file

DEFAULT_TIMEOUT_S = 900
_MAX_TIMEOUT_S = 3600
_PROTECTED_BRANCHES = {"main", "master"}
_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|SID)", re.IGNORECASE)
_NAME_NORM = re.compile(r"[\s_\-.]+")

# Flags that keep Aider non-interactive and unable to run anything but edits.
# Booleans are spelled out explicitly so a repo's .aider.conf.yml cannot turn
# them back on (configargparse: the command line wins over config files).
SAFE_FLAGS = (
    "--yes-always",
    "--no-stream",
    "--no-pretty",
    "--no-fancy-input",
    "--no-suggest-shell-commands",
    "--no-auto-lint",
    "--no-auto-test",
    "--no-detect-urls",
    "--disable-playwright",
    "--no-check-update",
    "--no-show-release-notes",
    "--no-show-model-warnings",
    "--no-restore-chat-history",
    "--analytics-disable",
    "--auto-commits",
)


# ── settings / registry ─────────────────────────────────────────────────────
def _registry_path() -> Path:
    return user_data_file("aider_projects.json")


def _load_registry() -> dict:
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_registry(data: dict) -> None:
    _registry_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _projects() -> dict[str, str]:
    return {str(k): str(v) for k, v in (_load_registry().get("projects") or {}).items()}


def _commits_made() -> dict[str, list[str]]:
    return {str(k): list(v) for k, v in (_load_registry().get("commits") or {}).items()}


def _remember_commits(project_dir: Path, shas: list[str]) -> None:
    if not shas:
        return
    data = _load_registry()
    commits = data.setdefault("commits", {})
    key = str(project_dir)
    commits[key] = (commits.get(key, []) + shas)[-200:]
    _save_registry(data)


def _norm_name(name: str) -> str:
    return _NAME_NORM.sub("", name).lower()


def aider_model() -> str:
    override = os.environ.get("JARVIS_AIDER_MODEL", "").strip()
    if override:
        return override
    return f"anthropic/{claude_model('strong')}"


def find_aider() -> str | None:
    override = os.environ.get("JARVIS_AIDER_PATH", "").strip()
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which("aider")
    if found:
        return found
    home = Path.home()
    for cand in (home / ".local" / "bin" / "aider", home / ".local" / "bin" / "aider.exe"):
        if cand.is_file():
            return str(cand)
    return None


def _available() -> bool:
    return bool(get_provider_api_key("anthropic"))


# ── project resolution ──────────────────────────────────────────────────────
def _search_roots() -> list[Path]:
    home = Path.home()
    roots = [Path(p) for p in os.environ.get("JARVIS_AIDER_ROOTS", "").split(os.pathsep) if p.strip()]
    roots += [home / "Desktop", home / "Documents", home / "Projects", home / "source" / "repos",
              home / "Desktop" / "JarvisProjects", home]
    if os.name == "nt":
        for drive in ("D:\\", "E:\\"):
            roots += [Path(drive) / "Projects", Path(drive)]
    seen, out = set(), []
    for r in roots:
        if str(r) not in seen and r.is_dir():
            seen.add(str(r))
            out.append(r)
    return out


def resolve_project(project: str) -> Path | None:
    """A project is a folder path, a registered name, or a folder name found
    (two levels deep) under the usual project roots."""
    project = (project or "").strip().strip('"')
    if not project:
        return None
    as_path = Path(os.path.expandvars(os.path.expanduser(project)))
    if as_path.is_absolute() and as_path.is_dir():
        return as_path.resolve()

    want = _norm_name(project)
    reg = _projects()
    for name, path in reg.items():
        if _norm_name(name) == want and Path(path).is_dir():
            return Path(path).resolve()
    for name, path in reg.items():
        if want and want in _norm_name(name) and Path(path).is_dir():
            return Path(path).resolve()

    for root in _search_roots():
        try:
            level1 = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            continue
        for p in level1:
            if _norm_name(p.name) == want:
                return p.resolve()
        for p in level1:
            try:
                for q in p.iterdir():
                    if q.is_dir() and _norm_name(q.name) == want:
                        return q.resolve()
            except OSError:
                continue
    return None


# ── git helpers ─────────────────────────────────────────────────────────────
def _git(project_dir: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout.strip()


def _head(project_dir: Path) -> str | None:
    try:
        return _git(project_dir, "rev-parse", "HEAD")
    except RuntimeError:
        return None          # repo without commits yet


def prepare_repo(project_dir: Path) -> str:
    """Make sure ``project_dir`` is a git repo and not on main/master.
    Returns a short note about what was done (may be empty)."""
    if shutil.which("git") is None:
        raise RuntimeError("git is not installed, sir. Install Git for Windows first.")
    notes = []
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=project_dir,
                            capture_output=True, text=True).returncode == 0
    if not inside:
        _git(project_dir, "init")
        notes.append("started a git repository there")
    if _head(project_dir) is None:
        return "; ".join(notes)
    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in _PROTECTED_BRANCHES:
        new = time.strftime("jarvis/aider-%Y%m%d-%H%M%S")
        _git(project_dir, "checkout", "-b", new)
        notes.append(f"working on a new branch {new} so {branch} stays untouched")
    return "; ".join(notes)


# ── running aider ───────────────────────────────────────────────────────────
_GIT_SECRET = re.compile(r"(TOKEN|PASSWORD|PASSWD)", re.IGNORECASE)


def _keep_env(name: str) -> bool:
    # git's own settings (GIT_CONFIG_KEY_n, GIT_AUTHOR_NAME, ...) look like
    # secrets to the generic filter but git breaks without them.
    if name.upper().startswith("GIT_"):
        return not _GIT_SECRET.search(name)
    return not _SECRET_ENV.search(name)


def child_env(api_key: str) -> dict:
    env = {k: v for k, v in os.environ.items() if _keep_env(k)}
    env["ANTHROPIC_API_KEY"] = api_key
    env["PYTHONIOENCODING"] = "utf-8"
    env["AIDER_ANALYTICS_DISABLE"] = "true"
    env["AIDER_CHECK_UPDATE"] = "false"
    return env


def build_command(aider: str, task: str, model: str, files: list[str]) -> list[str]:
    return [aider, "--model", model, *SAFE_FLAGS, "--message", task, *files]


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        proc.kill()


def run_aider(cmd: list[str], project_dir: Path, env: dict, timeout: int,
              cancel_event: threading.Event | None = None) -> tuple[int | None, str, str]:
    """Run Aider; returns (exit code or None, output tail, end reason)."""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    out_lines: list[str] = []
    proc = subprocess.Popen(cmd, cwd=project_dir, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", **kwargs)

    def _reader():
        for line in proc.stdout:            # type: ignore[union-attr]
            out_lines.append(line.rstrip())
            del out_lines[:-400]
    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    reason = "finished"
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            reason = "cancelled"
            _kill_tree(proc)
            break
        if time.monotonic() > deadline:
            reason = "timeout"
            _kill_tree(proc)
            break
        time.sleep(0.25)
    reader.join(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()
    return proc.poll(), "\n".join(out_lines[-40:]), reason


def _summary(project_dir: Path, before: str | None) -> tuple[list[str], str]:
    after = _head(project_dir)
    if not after or after == before:
        return [], ""
    rng = f"{before}..{after}" if before else after
    shas = _git(project_dir, "rev-list", "--reverse", rng, check=False).split()
    stat = _git(project_dir, "diff", "--stat", f"{before}..{after}", check=False) if before else \
        _git(project_dir, "show", "--stat", "--format=", after, check=False)
    return shas, stat


# ── actions ─────────────────────────────────────────────────────────────────
def _do_code(p: dict, cancel_event) -> str:
    task = str(p.get("task") or "").strip()
    if not task:
        return "Tell me what to change in the project, sir."
    project_dir = resolve_project(str(p.get("project") or ""))
    if project_dir is None:
        return (f"I couldn't find a project called '{p.get('project', '')}', sir. "
                "Give me its folder path, or register it with action add_project.")
    reason = path_guard.protected_reason(project_dir, write=True)
    if reason:
        return f"I can't let Aider edit {project_dir.name}: {reason}."

    api_key = get_provider_api_key("anthropic")
    if not api_key:
        return "Aider needs a Claude API key, sir. Add your Anthropic key in Settings first."
    aider = find_aider()
    if not aider:
        return ("Aider isn't installed yet, sir. In a terminal run: "
                "python -m pip install aider-install  then  aider-install")

    files = [f.strip() for f in str(p.get("files") or "").split(",") if f.strip()]
    for f in files:
        target = (project_dir / f).resolve()
        if not target.is_relative_to(project_dir):
            return f"'{f}' is outside the project folder, sir."

    note = prepare_repo(project_dir)
    before = _head(project_dir)
    timeout = max(60, min(int(p.get("timeout") or DEFAULT_TIMEOUT_S), _MAX_TIMEOUT_S))
    code, tail, end = run_aider(build_command(aider, task, aider_model(), files),
                                project_dir, child_env(api_key), timeout, cancel_event)
    shas, stat = _summary(project_dir, before)
    _remember_commits(project_dir, shas)
    branch = _git(project_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False)

    head = {"cancelled": "Stopped Aider as you asked.",
            "timeout": f"Aider ran past {timeout // 60} minutes, so I stopped it.",
            "finished": "Aider finished." if code == 0 else f"Aider exited with code {code}."}[end]
    lines = [f"{head} Project: {project_dir.name} (branch {branch})."]
    if note:
        lines.append(note[0].upper() + note[1:] + ".")
    if shas:
        lines.append(f"{len(shas)} commit(s). Say 'undo the last Aider change' to revert.")
        lines.append(stat[-1500:])
    else:
        lines.append("No files were changed.")
        if tail:
            lines.append("Aider said:\n" + tail[-1200:])
    return "\n".join(lines)


def _do_undo(p: dict) -> str:
    project_dir = resolve_project(str(p.get("project") or ""))
    if project_dir is None:
        return "Which project should I undo, sir?"
    head = _head(project_dir)
    mine = _commits_made().get(str(project_dir), [])
    if not head or head not in mine:
        return ("The latest commit there wasn't made by Aider through me, sir, "
                "so I won't revert it.")
    _git(project_dir, "revert", "--no-edit", head)
    data = _load_registry()
    data.setdefault("commits", {})[str(project_dir)] = [s for s in mine if s != head]
    _save_registry(data)
    return f"Reverted the last Aider change in {project_dir.name}, sir. History is kept."


def _do_changes(p: dict) -> str:
    project_dir = resolve_project(str(p.get("project") or ""))
    if project_dir is None:
        return "Which project, sir?"
    mine = set(_commits_made().get(str(project_dir), []))
    log = _git(project_dir, "log", "-15", "--format=%H %s", check=False).splitlines()
    rows = [line.split(" ", 1)[1] for line in log if line.split(" ", 1)[0] in mine]
    if not rows:
        return f"No Aider changes recorded for {project_dir.name}, sir."
    return f"Recent Aider changes in {project_dir.name}:\n" + "\n".join(f"- {r}" for r in rows)


def _do_add_project(p: dict) -> str:
    name = str(p.get("name") or "").strip()
    path = Path(os.path.expanduser(str(p.get("path") or "").strip()))
    if not name or not path.is_dir():
        return "Give me a project name and an existing folder path, sir."
    data = _load_registry()
    data.setdefault("projects", {})[name] = str(path.resolve())
    _save_registry(data)
    return f"Registered {name} at {path.resolve()}, sir."


def _do_list() -> str:
    reg = _projects()
    if not reg:
        return "No projects registered yet, sir. I can still find folders by name."
    return "Registered projects:\n" + "\n".join(f"- {k}: {v}" for k, v in reg.items())


def _do_status() -> str:
    aider = find_aider()
    return (f"Aider: {'installed at ' + aider if aider else 'not installed'}. "
            f"Model: {aider_model()}. Claude key: {'set' if _available() else 'missing'}.")


def aider_agent(parameters: dict, cancel_event=None) -> str:
    """Long-running: make a code change in an existing project."""
    try:
        return _do_code(parameters or {}, cancel_event)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return f"Aider task failed: {str(exc)[:300]}"


def aider_projects(parameters: dict) -> str:
    """Quick: undo, recent changes, project registry, status."""
    p = parameters or {}
    action = str(p.get("action") or "status").strip().lower()
    try:
        if action == "undo":
            return _do_undo(p)
        if action in ("changes", "diff", "history"):
            return _do_changes(p)
        if action == "add_project":
            return _do_add_project(p)
        if action in ("list", "list_projects"):
            return _do_list()
        if action == "status":
            return _do_status()
        return f"Unknown action '{action}', sir."
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return f"Aider task failed: {str(exc)[:300]}"


# ── Tool declarations (auto-discovered by core/action_loader.py) ─────────────
TOOL_CODE = {
    "name": "aider_agent",
    "description": (
        "Edits the owner's EXISTING local code projects with Aider (Claude-powered, "
        "multi-file, git-tracked, runs in the background). Use for 'fix/add/change X in my "
        "<project>' on a project that already exists anywhere on the PC. For a brand-new "
        "project use dev_agent; for a single standalone file use code_helper."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "task": {"type": "STRING",
                     "description": "The change to make, in full detail as the owner said it"},
            "project": {"type": "STRING", "description": "Project name or folder path"},
            "files": {"type": "STRING",
                      "description": "Optional comma-separated files (relative to the project) to focus on"},
            "timeout": {"type": "INTEGER",
                        "description": f"Seconds before Aider is stopped (default {DEFAULT_TIMEOUT_S})"},
        },
        "required": ["task", "project"],
    },
    "handler": aider_agent,
    "risk": "write",
    "timeout": 30,
    "long_running": True,
    "available": _available,
}

TOOL_MANAGE = {
    "name": "aider_projects",
    "description": (
        "Manage Aider coding work: undo the last Aider change in a project, list recent Aider "
        "changes, register a project name to a folder, list registered projects, or show "
        "whether Aider is installed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "undo | changes | add_project | list_projects | status"},
            "project": {"type": "STRING", "description": "Project name or folder path (undo, changes)"},
            "name": {"type": "STRING", "description": "For add_project: short project name"},
            "path": {"type": "STRING", "description": "For add_project: the project folder"},
        },
        "required": ["action"],
    },
    "handler": aider_projects,
    "risk": "write",
    "timeout": 30,
    "available": _available,
}

TOOLS = [TOOL_CODE, TOOL_MANAGE]

if __name__ == "__main__":      # quick manual check: python -m jarvis.actions.aider_agent
    print(_do_status())
    sys.exit(0)
