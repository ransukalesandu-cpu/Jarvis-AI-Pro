"""Skills: folders of instructions the assistant can load when a task needs them.

A skill is ``<name>/SKILL.md``::

    ---
    name: weekly-report
    description: Build the Friday status report from my notes and calendar.
    version: 1
    ---
    Step-by-step instructions in Markdown...

Two places are scanned: the built-in ``jarvis/skills/`` and the owner's
``<user data>/skills/``. Only the name and one-line description go into the
prompt (see :func:`index_text`); the body is loaded on demand with
``skills(action="use", name=...)``, so installing many skills costs almost nothing.

A skill is *instructions only*: it never runs code by itself. Anything it asks the
assistant to do goes through the normal tools and their confirmation tiers.
Creating or deleting a skill through the tool is DANGEROUS tier (see
``core/security.py``), because a saved skill steers every later session.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_BYTES = 32 * 1024
MAX_DESCRIPTION = 300
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BUILTIN_DIR = Path(__file__).resolve().parent.parent / "skills"


class SkillError(ValueError):
    """A skill file or request is invalid."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    version: str
    body: str
    source: str          # "builtin" | "user"
    path: Path
    enabled: bool = True


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Split ``---`` front matter (simple ``key: value`` lines) from the Markdown body."""
    text = (text or "").lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must start with a '---' front matter block")
    meta: dict[str, str] = {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise SkillError(f"front matter line {i + 1} is not 'key: value'")
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key.strip().lower()] = value
    if end is None:
        raise SkillError("front matter is not closed with '---'")
    return meta, "\n".join(lines[end + 1:]).strip()


def _build(path: Path, source: str, expected_name: str) -> Skill:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise SkillError(f"SKILL.md is larger than {MAX_BYTES // 1024} KB")
    meta, body = parse_skill_md(raw.decode("utf-8", errors="replace"))
    name = meta.get("name", "")
    if not NAME_RE.match(name):
        raise SkillError("name must be lowercase letters, digits, '-' or '_' (max 64)")
    if name != expected_name:
        raise SkillError(f"name '{name}' must match its folder '{expected_name}'")
    description = meta.get("description", "").strip()
    if not description:
        raise SkillError("description is required")
    if len(description) > MAX_DESCRIPTION:
        raise SkillError(f"description is longer than {MAX_DESCRIPTION} characters")
    if not body:
        raise SkillError("the skill body is empty")
    return Skill(name, description, meta.get("version", "1"), body, source, path)


class SkillRegistry:
    def __init__(self, user_dir: Optional[Path] = None, builtin_dir: Optional[Path] = BUILTIN_DIR,
                 state_path: Optional[Path] = None):
        self._user_dir = user_dir
        self._builtin_dir = builtin_dir
        self._state_path = state_path
        self._lock = threading.RLock()
        self.errors: dict[str, str] = {}

    # ── locations ────────────────────────────────────────────────────────────
    def user_dir(self) -> Path:
        if self._user_dir is not None:
            return self._user_dir
        from jarvis.core.user_data import user_data_dir
        return user_data_dir() / "skills"

    def _state_file(self) -> Path:
        if self._state_path is not None:
            return self._state_path
        from jarvis.core.user_data import user_data_file
        return user_data_file("skills_state.json")

    def _disabled(self) -> set[str]:
        try:
            return set(json.loads(self._state_file().read_text(encoding="utf-8")).get("disabled", []))
        except (OSError, ValueError, AttributeError):
            return set()

    # ── reading ──────────────────────────────────────────────────────────────
    def scan(self) -> list[Skill]:
        """All valid skills; the owner's folder overrides a built-in of the same name."""
        found: dict[str, Skill] = {}
        errors: dict[str, str] = {}
        disabled = self._disabled()
        for source, root in (("builtin", self._builtin_dir), ("user", self.user_dir())):
            if root is None or not Path(root).is_dir():
                continue
            for folder in sorted(Path(root).iterdir()):
                md = folder / "SKILL.md"
                if folder.name.startswith((".", "_")) or folder.is_symlink() or not md.is_file() or md.is_symlink():
                    continue
                try:
                    skill = _build(md, source, folder.name)
                except (SkillError, OSError) as exc:
                    errors[f"{source}/{folder.name}"] = str(exc)
                    continue
                found[skill.name] = Skill(**{**skill.__dict__, "enabled": skill.name not in disabled})
        with self._lock:
            self.errors = errors
        return sorted(found.values(), key=lambda s: s.name)

    def get(self, name: str) -> Optional[Skill]:
        return next((s for s in self.scan() if s.name == name), None)

    def index_text(self, max_chars: int = 1500) -> str:
        """One line per enabled skill for the system prompt ('' when there are none)."""
        lines = [f"- {s.name}: {s.description}" for s in self.scan() if s.enabled]
        if not lines:
            return ""
        text = ("Skills (owner-installed instructions). When a request matches one, load it with "
                "skills(action='use', name=...) and follow it:\n" + "\n".join(lines))
        return text[:max_chars]

    # ── changing (user folder only) ──────────────────────────────────────────
    def create(self, name: str, description: str, body: str, *, overwrite: bool = False) -> Skill:
        name = str(name or "").strip().lower()
        if not NAME_RE.match(name):
            raise SkillError("name must be lowercase letters, digits, '-' or '_' (max 64)")
        description = " ".join(str(description or "").split())
        text = f"---\nname: {name}\ndescription: {description}\nversion: 1\ncreated_by: assistant\n---\n{str(body or '').strip()}\n"
        folder = self.user_dir() / name
        md = folder / "SKILL.md"
        if md.exists() and not overwrite:
            raise SkillError(f"a skill named '{name}' already exists")
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "SKILL.md.tmp"
        tmp.write_text(text, encoding="utf-8")
        try:
            skill = _build(tmp, "user", name)
        except Exception:
            tmp.unlink(missing_ok=True)
            if not any(folder.iterdir()):
                folder.rmdir()
            raise
        tmp.replace(md)
        return Skill(**{**skill.__dict__, "path": md})

    def delete(self, name: str) -> bool:
        folder = self.user_dir() / str(name or "").strip().lower()
        md = folder / "SKILL.md"
        if not NAME_RE.match(folder.name) or not md.is_file() or folder.is_symlink():
            return False
        md.unlink()
        for leftover in folder.iterdir():
            if leftover.is_file():
                leftover.unlink()
        try:
            folder.rmdir()
        except OSError:
            pass
        return True

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if self.get(name) is None:
            return False
        with self._lock:
            disabled = self._disabled()
            (disabled.discard if enabled else disabled.add)(name)
            path = self._state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"disabled": sorted(disabled)}), encoding="utf-8")
            tmp.replace(path)
        return True


_REGISTRY: Optional[SkillRegistry] = None
_LOCK = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    with _LOCK:
        if _REGISTRY is None:
            _REGISTRY = SkillRegistry()
        return _REGISTRY


def reset_for_tests(registry: Optional[SkillRegistry] = None) -> None:
    global _REGISTRY
    with _LOCK:
        _REGISTRY = registry
