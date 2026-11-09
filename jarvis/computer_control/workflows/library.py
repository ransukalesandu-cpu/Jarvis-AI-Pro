"""Workflow learning and reuse (Project 5, ideas from OpenAdapt).

OpenAdapt records raw input events and replays/generalises them. JARVIS records
at a higher level — the *verified steps* of a task it just ran (tool + args +
expectations) — because those survive layout changes far better than mouse
positions, and every replay goes through the same policy/approval/verification
pipeline as a fresh task.

Lifecycle:

* **record** — :func:`draft_from_report` turns a successful :class:`TaskReport`
  into a draft. Only verified, successful steps are kept; password text is
  replaced by a ``{{param:password}}`` placeholder (never stored); everything
  is redacted; arguments that came from earlier results stay marked tainted.
* **save** — only with the owner's approval (``workflow.save`` is HIGH, so the
  native prompt asks). A new save of the same name becomes the next version.
* **validate** — before every run: every tool still exists, the plan still
  builds, and the apps/windows it needs are discoverable (read-only checks).
* **run** — replays through the Host Agent with verification; parameters are
  filled in at run time. A workflow is *trusted* only after
  ``TRUST_AFTER`` consecutive verified successes; until then each run needs
  the owner's approval, and one failure resets the streak.
* **track** — success/failure counts, last result and duration per version.

Storage: the steps live in a small bounded JSON file in the user-data folder
(``MAX_WORKFLOWS``); the outline and statistics are mirrored to Supabase through
the existing personal-memory ``workflow_save`` operation when cloud memory is
configured (best effort, metadata only — its schema stores titles and kinds).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from jarvis.computer_control.redaction import redact_params, redact_text

TRUST_AFTER = 3
MAX_WORKFLOWS = 40
MAX_STEPS = 16
_NAME_RE = re.compile(r"^[\w .-]{1,60}$")
PASSWORD_PARAM = "{{param:password}}"


@dataclass
class WorkflowStep:
    tool: str
    args: dict
    description: str = ""
    expect: dict = field(default_factory=dict)
    tainted: bool = False


@dataclass
class Workflow:
    name: str
    objective: str
    steps: list
    version: int = 1
    params: list = field(default_factory=list)       # names required at run time
    created: float = field(default_factory=time.time)
    successes: int = 0
    failures: int = 0
    streak: int = 0                                  # consecutive verified successes
    last_result: str = ""
    last_run: float = 0.0
    last_duration_s: float = 0.0

    @property
    def trusted(self) -> bool:
        return self.streak >= TRUST_AFTER

    @property
    def key(self) -> str:
        # readable slug + a hash of the whole normalized name, always: distinct names never
        # share a key, even one that spells out another name's key ("daily-note-2cbd8000")
        slug = re.sub(r"[^a-z0-9_-]+", "-", self.identity).strip("-")[:40] or "workflow"
        return f"{slug}-{hashlib.sha256(self.identity.encode('utf-8')).hexdigest()[:16]}"

    @property
    def identity(self) -> str:
        """The name as it is compared: whitespace-normalized and case-folded."""
        return " ".join(self.name.split()).casefold()

    def as_dict(self) -> dict:
        data = asdict(self)
        data["trusted"] = self.trusted
        return data

    def summary(self) -> str:
        state = "trusted" if self.trusted else f"supervised ({self.streak}/{TRUST_AFTER} verified runs)"
        return (f"'{self.name}' v{self.version}: {len(self.steps)} steps, {self.successes} ok / "
                f"{self.failures} failed, {state}")


class WorkflowError(ValueError):
    pass


def draft_from_report(report, name: str) -> Workflow:
    """A draft from a finished task — only if every step really succeeded."""
    name = " ".join(str(name or "").split())
    if not _NAME_RE.match(name):
        raise WorkflowError("Give the workflow a short name (letters, numbers, spaces, - . _).")
    if not getattr(report, "success", False):
        raise WorkflowError("Only a task that finished successfully can be saved as a workflow.")
    last: dict[int, Any] = {}
    for entry in report.trace:
        if not entry.recovery:
            last[entry.step] = entry
    steps: list[WorkflowStep] = []
    params: set[str] = set()
    for index in sorted(last):
        entry = last[index]
        if entry.status != "ok" or entry.verified is False:
            raise WorkflowError(f"Step {index + 1} did not succeed, so the task cannot become a workflow.")
        args = dict(entry.args)
        password = bool(args.get("is_password") or str(args.get("text")) == "[password-field]")
        if entry.verified is not True and str(getattr(entry, "level", "")) != "low" and not password:
            # only read-only steps, and password entry (never read back by design), may be
            # kept without independent verification
            raise WorkflowError(f"Step {index + 1} changed something but its result was not checked, "
                                "so the task cannot become a workflow.")
        if password:
            args["text"] = PASSWORD_PARAM
            params.add("password")
        dropped = {"is_password", "label", "app", "_cc"} | ({"text"} if password else set())
        lossy = [k for k in getattr(entry, "altered", []) or [] if k not in dropped]
        if lossy:
            # the trace holds a redacted/truncated copy; replaying it would type the wrong thing
            raise WorkflowError(f"Step {index + 1} used a value that cannot be stored exactly "
                                f"({', '.join(lossy)}: a secret or very long text), so the task "
                                "cannot become a workflow.")
        args = {k: v for k, v in args.items() if k not in ("is_password", "label", "app", "_cc")}
        steps.append(WorkflowStep(tool=entry.tool, args=redact_params(args),
                                  description=redact_text(entry.description, 100),
                                  tainted=bool(getattr(entry, "tainted", False))))
    if not steps:
        raise WorkflowError("The task has no steps to save.")
    if len(steps) > MAX_STEPS:
        raise WorkflowError(f"A workflow can have at most {MAX_STEPS} steps.")
    return Workflow(name=name, objective=redact_text(report.objective, 400), steps=[asdict(s) for s in steps],
                    params=sorted(params))


class LocalStore:
    """Bounded JSON file: {key: [version dicts, newest last]}."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()

    def path(self) -> Path:
        if self._path is None:
            from jarvis.core.user_data import user_data_file
            self._path = user_data_file("cc_workflows.json")
        return self._path

    def _load(self) -> dict:
        """The stored workflows. A missing file is empty; any other read error raises,
        so ``put``/``delete`` never overwrite data they could not read. A corrupt file
        is moved aside (kept for recovery) before it is treated as empty."""
        try:
            data = json.loads(self.path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except ValueError:
            aside = self.path().with_name(f"{self.path().stem}.corrupt-{int(time.time())}.json")
            self.path().replace(aside)
            return {}
        if not isinstance(data, dict):
            raise WorkflowError(f"{self.path().name} does not hold a workflow table; it was left as is.")
        return data

    def _load_quiet(self) -> dict:
        try:
            return self._load()
        except (OSError, WorkflowError):
            from jarvis.core import failsoft
            failsoft.suppress("computer_control.workflows:load")
            return {}

    def _save(self, data: dict) -> None:
        if len(data) > MAX_WORKFLOWS:
            oldest = sorted(data, key=lambda k: data[k][-1].get("last_run") or data[k][-1].get("created", 0))
            for key in oldest[: len(data) - MAX_WORKFLOWS]:
                data.pop(key, None)
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path())

    def put(self, wf: Workflow, *, new_version: bool) -> Workflow:
        with self._lock:
            data = self._load()
            versions = data.setdefault(wf.key, [])
            if versions and _from_record(versions[-1]).identity != wf.identity:
                # a key collision must never turn one workflow into a version of another
                raise WorkflowError(f"'{wf.name}' clashes with the stored workflow "
                                    f"'{versions[-1].get('name')}'; choose another name.")
            if new_version:
                wf.version = (versions[-1]["version"] + 1) if versions else 1
                versions.append(_to_record(wf))
                del versions[:-5]                       # keep the last 5 versions
            elif versions:
                versions[-1] = _to_record(wf)
            else:
                versions.append(_to_record(wf))
            self._save(data)
            return wf

    def get(self, name: str, version: Optional[int] = None) -> Optional[Workflow]:
        key = Workflow(name=name, objective="", steps=[]).key
        versions = self._load_quiet().get(key) or []
        if version is not None:
            versions = [v for v in versions if v.get("version") == version]
        return _from_record(versions[-1]) if versions else None

    def all(self) -> list[Workflow]:
        return [_from_record(v[-1]) for v in self._load_quiet().values() if v]

    def delete(self, name: str) -> bool:
        with self._lock:
            data = self._load()
            key = Workflow(name=name, objective="", steps=[]).key
            if data.pop(key, None) is None:
                return False
            self._save(data)
            return True


def _to_record(wf: Workflow) -> dict:
    data = asdict(wf)
    return data


def _from_record(row: dict) -> Workflow:
    fields_ = {k: row[k] for k in Workflow.__dataclass_fields__ if k in row}
    return Workflow(**fields_)


def cloud_sync(wf: Workflow) -> bool:
    """Mirror name/objective/outline/stats to Supabase (metadata only). Best effort."""
    try:
        from jarvis.core.personal_cloud_memory import save_cloud_agent_workflow
        save_cloud_agent_workflow({
            "workflow_id": f"cc-{wf.key}"[:100],
            "name": wf.name[:80],
            "objective": wf.objective[:500] or wf.name,
            "criteria": [f"cc v{wf.version}; ok {wf.successes}; failed {wf.failures}; "
                         f"{'trusted' if wf.trusted else 'supervised'}"[:160]],
            "steps": [{"title": str(s.get("description") or s.get("tool"))[:100],
                       "kind": f"{s.get('tool')}:{s.get('args', {}).get('op', '')}"[:40]}
                      for s in wf.steps[:MAX_STEPS]],
        })
        return True
    except Exception:
        from jarvis.core import failsoft
        failsoft.suppress("computer_control.workflows:cloud_sync")
        return False
