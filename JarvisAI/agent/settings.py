"""Autonomy settings, stored next to the existing configuration.

``config/api_keys.json`` is already the app's single user-editable store and is
git-ignored and written atomically with owner-only permissions, so the agent adds
keys there instead of inventing a second settings file. Environment variables
win, which is what CI and the headless runner use.

Keys (all optional):

    autonomous_enabled        bool   master switch for autonomous tasks
    autonomous_allow_shell    bool   allow the plan to run commands
    autonomous_allow_files    bool   allow writing files inside the workspace
    autonomous_allow_desktop  bool   allow mouse/keyboard control
    autonomous_dry_run        bool   resolve targets but never move the pointer
    autonomous_max_runtime_s  number hard wall-clock budget per task
    autonomous_retry_budget   number retries across a task
    autonomous_screen_paused  bool   owner turned screen access off
    vision_model              str    Gemini vision model id
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any


def _truthy(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "on", "enabled"}


def _number(value: Any, default: float, *, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AgentSettings:
    enabled: bool = True
    allow_shell: bool = True
    allow_files: bool = True
    allow_desktop: bool = True
    dry_run: bool = False
    screen_paused: bool = False
    max_runtime_s: float = 1800.0
    retry_budget: int = 12
    max_steps: int = 12
    vision_model: str = ""
    autonomy_voice_updates: bool = True
    # The HUD surfaces (dashboard card, rail button, menu entries, the minimised
    # status widget) are opt-in: they change the composition of a HUD that is
    # deliberately clean. The engine, the voice tool and the report work either
    # way.
    ui_enabled: bool = False

    @classmethod
    def load(cls, config: dict[str, Any] | None = None) -> "AgentSettings":
        data = config if config is not None else _read_config()
        env = os.environ
        settings = cls(
            enabled=_truthy(env.get("JARVIS_AUTONOMOUS") or data.get("autonomous_enabled"), True),
            allow_shell=_truthy(data.get("autonomous_allow_shell"), True),
            allow_files=_truthy(data.get("autonomous_allow_files"), True),
            allow_desktop=_truthy(data.get("autonomous_allow_desktop"), True),
            dry_run=_truthy(env.get("JARVIS_AGENT_DRY_RUN") or data.get("autonomous_dry_run"), False),
            screen_paused=_truthy(data.get("autonomous_screen_paused"), False),
            max_runtime_s=_number(
                env.get("JARVIS_AGENT_MAX_RUNTIME") or data.get("autonomous_max_runtime_s"),
                1800.0, low=30.0, high=14400.0,
            ),
            retry_budget=int(_number(data.get("autonomous_retry_budget"), 12, low=0, high=60)),
            max_steps=int(_number(data.get("autonomous_max_steps"), 12, low=3, high=16)),
            vision_model=str(data.get("vision_model") or "").strip(),
            autonomy_voice_updates=_truthy(data.get("autonomous_voice_updates"), True),
            ui_enabled=_truthy(env.get("JARVIS_AUTONOMOUS_UI")
                               or data.get("autonomous_ui_enabled"), False),
        )
        return settings

    def merged(self, **overrides: Any) -> "AgentSettings":
        return replace(self, **{key: value for key, value in overrides.items()
                                if value is not None})

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allow_shell": self.allow_shell,
            "allow_files": self.allow_files,
            "allow_desktop": self.allow_desktop,
            "dry_run": self.dry_run,
            "screen_paused": self.screen_paused,
            "max_runtime_s": self.max_runtime_s,
            "retry_budget": self.retry_budget,
            "max_steps": self.max_steps,
            "vision_model": self.vision_model,
            "autonomy_voice_updates": self.autonomy_voice_updates,
            "ui_enabled": self.ui_enabled,
        }

    def capability_notes(self) -> list[str]:
        """Human-readable consequences of the current settings."""
        notes: list[str] = []
        if not self.enabled:
            notes.append("Autonomous tasks are switched off.")
        if self.screen_paused:
            notes.append("Screen access is paused by the owner.")
        if not self.allow_desktop:
            notes.append("Desktop control is disabled; the agent will re-plan instead.")
        if self.dry_run:
            notes.append("Dry-run: desktop targets are resolved but never clicked.")
        if not self.allow_shell:
            notes.append("Shell commands are disabled; only vision steps can run.")
        return notes


def save_settings(values: dict[str, Any]) -> None:
    """Persist a subset of agent settings without touching unrelated keys."""
    try:
        from memory.config_manager import load_api_keys, write_api_config
    except Exception as exc:  # pragma: no cover - config module is always present
        raise RuntimeError(f"JARVIS configuration is unavailable: {exc}") from exc
    data = load_api_keys()
    for key in (
        "autonomous_enabled", "autonomous_allow_shell", "autonomous_allow_files",
        "autonomous_allow_desktop", "autonomous_dry_run", "autonomous_max_runtime_s",
        "autonomous_retry_budget", "autonomous_max_steps", "autonomous_screen_paused",
        "autonomous_voice_updates", "autonomous_ui_enabled", "vision_model",
    ):
        if key in values:
            data[key] = values[key]
    write_api_config(data)


def _read_config() -> dict[str, Any]:
    try:
        from memory.config_manager import load_api_keys

        data = load_api_keys()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
