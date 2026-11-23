"""Owner-written routines with trigger phrases (``routines.yaml`` / ``routines.json``).

Voice-saved routines (core/routines.py) record what JARVIS just did. This file
is the other way round: the owner writes the steps once, by hand, and gives
each routine the phrases that start it::

    morning:
      description: Start the day
      phrases: ["good morning", "morning mode"]
      steps:
        - {tool: open_app, args: {app_name: Outlook}}
        - {tool: phone_control, args: {action: mute_volume}}
        - {tool: weather_report, args: {}}

Location: ``<user data>/routines.yaml`` (needs PyYAML) or ``routines.json``
(same structure). JARVIS can read and run these but never writes the file,
the same rule as ``mcp_servers.json``: a saved routine steers future
sessions, so only the owner edits it.

A phrase only fires on an exact match of the whole sentence (case and
punctuation ignored, an optional "jarvis" in front), so ordinary speech that
merely mentions "morning" does not start anything.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from jarvis.core.routines import normalize_name, validate_steps

FILE_NAMES = ("routines.yaml", "routines.yml", "routines.json")
MAX_ROUTINES = 50
_cache: dict = {"key": None, "routines": {}, "errors": []}
_lock = threading.Lock()


def _dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir()


def find_file(base: Optional[Path] = None) -> Optional[Path]:
    base = base or _dir()
    for name in FILE_NAMES:
        p = base / name
        if p.is_file():
            return p
    return None


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("routines.yaml needs PyYAML (pip install pyyaml), or use routines.json") from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    if isinstance(data, dict) and isinstance(data.get("routines"), dict):
        data = data["routines"]
    if not isinstance(data, dict):
        raise ValueError("the routines file must map routine names to {phrases, steps}")
    return data


def _normalize_phrase(text: str) -> str:
    try:
        key = normalize_name(text)
    except ValueError:
        return ""
    for prefix in ("hey jarvis ", "jarvis ", "ok jarvis "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    return key


def load(base: Optional[Path] = None) -> tuple[dict[str, dict], list[str]]:
    """{normalized name: {name, description, phrases, steps, source}}, errors. Cached by mtime."""
    path = find_file(base)
    if path is None:
        return {}, []
    try:
        key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
    except OSError:
        return {}, []
    with _lock:
        if _cache["key"] == key:
            return _cache["routines"], _cache["errors"]
    routines: dict[str, dict] = {}
    errors: list[str] = []
    try:
        raw = _parse(path)
    except (ValueError, OSError) as exc:
        errors.append(f"{path.name}: {exc}")
        raw = {}
    except Exception as exc:   # YAML/JSON syntax errors carry their own types
        errors.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:200]}")
        raw = {}
    for name, body in list(raw.items())[:MAX_ROUTINES]:
        try:
            if not isinstance(body, dict):
                raise ValueError("expected {phrases, steps}")
            norm = normalize_name(str(name))
            steps = validate_steps([{"tool": s.get("tool"), "args": s.get("args") or {}}
                                    for s in (body.get("steps") or []) if isinstance(s, dict)])
            phrases = body.get("phrases") or []
            if isinstance(phrases, str):
                phrases = [phrases]
            phrases = [p for p in (_normalize_phrase(str(x)) for x in phrases) if p]
            routines[norm] = {"name": str(name), "description": str(body.get("description") or ""),
                              "phrases": phrases, "steps": steps, "source": "file"}
        except ValueError as exc:
            errors.append(f"routine '{name}': {exc}")
    with _lock:
        _cache.update(key=key, routines=routines, errors=errors)
    return routines, errors


def get(name: str, base: Optional[Path] = None) -> Optional[dict]:
    try:
        norm = normalize_name(name)
    except ValueError:
        return None
    return load(base)[0].get(norm)


def match_phrase(text: str, base: Optional[Path] = None) -> Optional[str]:
    """Routine name whose phrase is exactly ``text`` (or "start/run <name>"), else None."""
    said = _normalize_phrase(text)
    if not said:
        return None
    routines, _ = load(base)
    for norm, r in routines.items():
        if said in r["phrases"]:
            return norm
    for verb in ("start ", "run ", "begin "):
        if said.startswith(verb):
            rest = said[len(verb):]
            for candidate in (rest, rest.removesuffix(" routine"), rest.removesuffix(" mode")):
                if candidate in routines:
                    return candidate
    return None


def clear_cache() -> None:
    with _lock:
        _cache.update(key=None, routines={}, errors=[])
