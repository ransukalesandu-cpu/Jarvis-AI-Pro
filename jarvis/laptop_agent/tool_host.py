"""Runs the Phase 1 laptop tools inside the agent, unchanged, and lazily.

* Which tools: every actions/*.py the hub does not run itself
  (hub/live.HUB_ACTION_FILES), plus the Android tools.
* Unchanged: a tool module is imported and run by the same
  core.action_loader.ActionRegistry as in Phase 1, with the same arguments.
* Lazily: the declarations come from a scan in a short-lived child process
  (cached by file size and modification time), and a module is imported in
  the agent only the first time one of its tools is called. That keeps the
  agent small (the budget is ~100 MB) when most tools are never used.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from jarvis.laptop_agent import android_tools

JARVIS_DIR = Path(__file__).resolve().parent.parent
ACTIONS_DIR = JARVIS_DIR / "actions"


def device_side_files(actions_dir: Path = ACTIONS_DIR) -> list[Path]:
    from jarvis.hub.live import HUB_ACTION_FILES
    return sorted(p for p in actions_dir.glob("*.py")
                  if not p.name.startswith("_") and p.name not in HUB_ACTION_FILES)


def _signature(files: list[Path]) -> str:
    return json.dumps([[p.name, p.stat().st_size, int(p.stat().st_mtime)] for p in files])


def scan(actions_dir: Path = ACTIONS_DIR) -> list[dict]:
    """Import every device-side action and describe its tools (child process)."""
    from jarvis.core.action_loader import discover_actions
    names = {p.name for p in device_side_files(actions_dir)}
    registry = discover_actions(actions_dir, logger=lambda _m: None,
                                include=lambda p: p.name in names)
    out = []
    for rec in registry._all_records:
        if not rec.valid:
            continue
        decl = {"name": rec.name, "description": rec.description, "parameters": rec.parameters}
        if rec.behavior:
            decl["behavior"] = rec.behavior
        out.append({"declaration": decl, "file": rec.file,
                    "meta": {"risk": rec.meta.risk, "timeout": rec.meta.timeout,
                             "long_running": rec.meta.long_running}})
    return out


def merge_declarations(laptop: dict, android: dict) -> dict:
    """One declaration for a name that exists on both kinds of device."""
    merged = copy.deepcopy(laptop)
    props = merged.setdefault("parameters", {"type": "OBJECT"}).setdefault("properties", {})
    for key, value in (android.get("parameters") or {}).get("properties", {}).items():
        props.setdefault(key, value)
    merged["description"] = f"{laptop.get('description', '').rstrip('.')}. {android.get('description', '')}"
    merged["parameters"].pop("required", None)      # requirements differ per device kind
    return merged


class ToolHost:
    def __init__(self, android: android_tools.AndroidTools | None, *, state_dir: Path,
                 actions_dir: Path = ACTIONS_DIR):
        self.android = android
        self.actions_dir = actions_dir
        self.cache_path = Path(state_dir) / "agent_tools.json"
        self._registries: dict[str, object] = {}
        self._file_of: dict[str, str] = {}
        self._lock = threading.Lock()
        self.laptop_tools: list[dict] = []

    # ── declarations ────────────────────────────────────────────────────────
    def load_declarations(self) -> list[dict]:
        files = device_side_files(self.actions_dir)
        sig = _signature(files)
        rows = None
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if cached.get("signature") == sig:
                rows = cached["tools"]
        except (OSError, ValueError, KeyError):
            rows = None
        if rows is None:
            proc = subprocess.run([sys.executable, "-m", "jarvis.laptop_agent", "scan"],
                                  cwd=str(JARVIS_DIR.parent), capture_output=True, text=True, timeout=300,
                                  env={**os.environ, "PYTHONPATH": str(JARVIS_DIR.parent)})
            if proc.returncode != 0:
                raise RuntimeError("tool scan failed: " + proc.stderr.strip()[-500:])
            rows = json.loads(proc.stdout.strip().splitlines()[-1])
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({"signature": sig, "tools": rows}), encoding="utf-8")
        self.laptop_tools = rows
        self._file_of = {r["declaration"]["name"]: r["file"] for r in rows}
        return self.announcement()

    def announcement(self) -> list[dict]:
        out = {r["declaration"]["name"]: dict(r) for r in self.laptop_tools}
        if self.android is not None and self.android.manager.devices:
            for decl in android_tools.DECLARATIONS:
                meta = android_tools.META.get(decl["name"], {"risk": "write", "timeout": 60})
                if decl["name"] in out:
                    row = out[decl["name"]]
                    row["declaration"] = merge_declarations(row["declaration"], decl)
                else:
                    out[decl["name"]] = {"declaration": decl, "meta": meta, "file": None}
        return list(out.values())

    # ── execution ───────────────────────────────────────────────────────────
    def _registry(self, file: str):
        with self._lock:
            reg = self._registries.get(file)
            if reg is None:
                from jarvis.core.action_loader import discover_actions
                reg = discover_actions(self.actions_dir, logger=lambda m: print(f"[Agent] {m}"),
                                       include=lambda p: p.name == file)
                self._registries[file] = reg
            return reg

    def run(self, name: str, args: dict, device: str, ctx: dict) -> str:
        android = self.android
        if android is not None and android.is_android(device):
            if name in android.names():
                return android.run(name, args, device, ctx)
            return (f"{name.replace('_', ' ')} runs on the laptop. For the {device} use device_shell, "
                    "open_app, tap, type_text or ui_automate.")
        if name in android_tools.LAPTOP_EQUIVALENTS and name not in self._file_of:
            target, mapper = android_tools.LAPTOP_EQUIVALENTS[name]
            return self.run(target, mapper(args), device, ctx)
        file = self._file_of.get(name)
        if not file:
            return f"The laptop has no tool called {name}."
        return self._registry(file).run(name, args, ctx) or "Done."
