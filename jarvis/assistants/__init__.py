"""Assistant profiles (Cherry Studio parity P9). See docs/ASSISTANT_PROFILES.md.

A profile is a named role JARVIS can switch into: its own instructions, an optional
preferred text provider, an optional knowledge base, and an optional tool allow-list.
JARVIS's identity, voice and security never change; a profile only adds focus.

Stored in ``<data>/assistants.json``.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 _\-]{0,39}$")
MAX_INSTRUCTIONS = 2000
# Never blocked by a profile's allow-list: switching back, stopping and safety tools.
ALWAYS_ALLOWED = frozenset({"assistant_profiles", "cc_emergency_stop", "cc_engine_status", "show_recent_actions",
                            "show_task_progress", "job_status", "security_settings", "knowledge", "notes"})
_lock = threading.RLock()

BUILTIN: dict[str, dict] = {
    "coding": {"instructions": "Act as a senior software engineer. Prefer precise, tested code, explain trade-offs "
                               "briefly, and ask before large refactors.", "provider": "claude"},
    "writer": {"instructions": "Act as a professional writer and editor. Clear structure, natural tone, no filler.",
               "provider": "claude"},
    "designer": {"instructions": "Act as a UI/UX designer. Think in user flows, hierarchy, spacing, accessibility "
                                 "and modern visual trends; give concrete, buildable suggestions."},
    "tutor": {"instructions": "Act as a patient tutor. Explain step by step with small examples and check "
                              "understanding with one short question."},
}


def _path() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "assistants.json"


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("profiles"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"active": "", "profiles": {}}


def _save(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    n = re.sub(r"\s*(assistant|mode|profile)$", "", n).strip()
    if not NAME_RE.match(n):
        raise ValueError("profile names use letters, digits, spaces, '-' or '_' (max 40)")
    return n


def all_profiles() -> dict[str, dict]:
    with _lock:
        merged = {k: dict(v, builtin=True) for k, v in BUILTIN.items()}
        merged.update({k: dict(v, builtin=False) for k, v in _load()["profiles"].items()})
        return merged


def save_profile(name: str, instructions: str, *, provider: str = "", knowledge_base: str = "",
                 allowed_tools: Optional[list[str]] = None) -> str:
    name = clean_name(name)
    instructions = str(instructions or "").strip()
    if not instructions:
        raise ValueError("a profile needs instructions")
    profile: dict = {"instructions": instructions[:MAX_INSTRUCTIONS]}
    if provider:
        from jarvis.core import text_brain
        p = text_brain.normalize(provider)
        if p not in text_brain.PROVIDERS:
            raise ValueError(f"unknown provider '{provider}'")
        profile["provider"] = p
    if knowledge_base:
        profile["knowledge_base"] = str(knowledge_base).strip().lower()[:48]
    tools = [t.strip() for t in (allowed_tools or []) if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", str(t).strip())]
    if tools:
        profile["allowed_tools"] = sorted(set(tools))
    with _lock:
        data = _load()
        data["profiles"][name] = profile
        _save(data)
    return name


def delete_profile(name: str) -> None:
    name = clean_name(name)
    with _lock:
        data = _load()
        if name not in data["profiles"]:
            raise KeyError(f"no custom profile named '{name}'" + (" (built-in profiles cannot be deleted)" if name in BUILTIN else ""))
        del data["profiles"][name]
        if data.get("active") == name:
            data["active"] = ""
        _save(data)


def active_name() -> str:
    return str(_load().get("active") or "")


def active() -> Optional[dict]:
    name = active_name()
    return dict(all_profiles().get(name, {}), name=name) if name and name in all_profiles() else None


def activate(name: str) -> dict:
    """Switch profile ('' / 'default' / 'jarvis' returns to plain JARVIS)."""
    raw = str(name or "").strip().lower()
    with _lock:
        data = _load()
        if raw in ("", "default", "jarvis", "normal", "none", "off"):
            data["active"] = ""
            _save(data)
            return {}
        name = clean_name(raw)
        profiles = all_profiles()
        if name not in profiles:
            raise KeyError(f"no profile named '{name}'")
        data["active"] = name
        _save(data)
    prof = profiles[name]
    if prof.get("knowledge_base"):
        try:
            from jarvis.knowledge import get_store
            get_store().set_active(prof["knowledge_base"])
        except (KeyError, ValueError):
            pass
    return dict(prof, name=name)


def prompt_block() -> str:
    """Added to the live system instruction while a profile is active."""
    prof = active()
    if not prof:
        return ""
    lines = [f"[ACTIVE ASSISTANT PROFILE: {prof['name']}] You are still JARVIS with the same identity, voice and "
             "security rules; this profile only adds focus for the owner's work.", prof["instructions"]]
    if prof.get("knowledge_base"):
        lines.append(f"Prefer the '{prof['knowledge_base']}' knowledge base (knowledge tool) for the owner's documents.")
    if prof.get("allowed_tools"):
        lines.append("Tools available in this profile: " + ", ".join(prof["allowed_tools"]) + ".")
    return "\n".join(lines)


def tool_block_reason(tool: str) -> str:
    """'' when the active profile allows ``tool``, else a short refusal for the model."""
    try:
        prof = active()
    except Exception:
        return ""
    allowed = (prof or {}).get("allowed_tools")
    if not allowed or tool in ALWAYS_ALLOWED or tool in allowed:
        return ""
    return (f"The active '{prof['name']}' profile does not use the {tool} tool. "
            "Say 'switch to default' (or another profile) to use it.")


def preferred_provider() -> str:
    prof = active()
    return str((prof or {}).get("provider") or "")
