"""Action policy: LOW / MEDIUM / HIGH, decided from the action itself.

The classification never trusts the plan's own description of an action. It
looks at the action id, its arguments and where the request came from:

* ``LOW``    — opening apps, reading public information, ordinary navigation,
               viewing allowed files, inspecting windows/controls. Runs at once.
* ``MEDIUM`` — creating/editing/moving files, typing, clicking ordinary controls,
               changing ordinary app preferences. Runs at once (and is logged).
* ``HIGH``   — deleting files, installing software, admin/system commands,
               system settings, sending messages, purchases, account/security
               changes, anything touching a protected path. Needs the owner's
               approval through the native prompt (AuthManager / PIN) every time,
               even with Full Access on.

Escalation rules (they only ever raise a level, never lower it):

* unknown action ids are HIGH;
* any path argument inside the protected list (JARVIS secrets / API-key files,
  the JARVIS install folder, Windows system directories) is HIGH;
* destructive words in a control's label ("Delete", "Send", "Pay", ...) are HIGH;
* typing into a shell / Run box, or hotkeys that open one, are HIGH;
* non-web URL schemes (``file:``, ``javascript:``, ``data:``) are HIGH;
* arguments derived from untrusted content (``tainted``) go up one level;
* a request whose *origin* is untrusted content is refused outright unless it
  is LOW (content can never make JARVIS change state).

Folders are default-allow (owner decision 5): everything outside the protected
list is treated like any other argument.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional


class Level(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def order(self) -> int:
        return {Level.LOW: 0, Level.MEDIUM: 1, Level.HIGH: 2}[self]

    def raised(self) -> "Level":
        return {Level.LOW: Level.MEDIUM, Level.MEDIUM: Level.HIGH, Level.HIGH: Level.HIGH}[self]

    @property
    def tool_risk(self) -> str:
        """The matching ``risk`` value of core/tool_runtime.py."""
        return {Level.LOW: "read", Level.MEDIUM: "write", Level.HIGH: "destructive"}[self]

    @classmethod
    def parse(cls, value: Any) -> Optional["Level"]:
        text = str(getattr(value, "value", value) or "").strip().lower()
        for level in cls:
            if level.value == text:
                return level
        return None


def max_level(*levels: Level) -> Level:
    return max(levels, key=lambda lv: lv.order)


class Origin(str, Enum):
    OWNER = "owner"          # the owner's own voice/typed request
    PLAN = "plan"            # a step JARVIS planned for an owner request
    UNTRUSTED = "untrusted"  # text found in a page/screenshot/document/tool output


# ── the action vocabulary ────────────────────────────────────────────────────
#: Base level of every action the engine knows. Anything else is HIGH.
BASE_LEVELS: dict[str, Level] = {
    # applications
    "app.list": Level.LOW, "app.running": Level.LOW, "app.launch": Level.LOW,
    "app.state": Level.LOW, "app.close": Level.MEDIUM, "app.preferences": Level.MEDIUM,
    "app.kill": Level.HIGH, "app.install": Level.HIGH, "app.uninstall": Level.HIGH,
    # windows
    "window.list": Level.LOW, "window.find": Level.LOW, "window.activate": Level.LOW,
    "window.inspect": Level.LOW, "window.wait": Level.LOW,
    "window.move": Level.MEDIUM, "window.resize": Level.MEDIUM,
    "window.minimize": Level.MEDIUM, "window.maximize": Level.MEDIUM,
    "window.restore": Level.MEDIUM, "window.close": Level.MEDIUM,
    # controls (accessibility first)
    "element.find": Level.LOW, "element.inspect": Level.LOW, "element.tree": Level.LOW,
    "element.read": Level.LOW, "element.wait": Level.LOW,
    "element.click": Level.MEDIUM, "element.invoke": Level.MEDIUM,
    "element.set_text": Level.MEDIUM, "element.select": Level.MEDIUM,
    "element.toggle": Level.MEDIUM, "menu.select": Level.MEDIUM,
    "dialog.respond": Level.MEDIUM,
    # raw input (fallback only)
    "input.move": Level.LOW, "input.scroll": Level.LOW, "input.position": Level.LOW,
    "input.click": Level.MEDIUM, "input.double_click": Level.MEDIUM,
    "input.right_click": Level.MEDIUM, "input.drag": Level.MEDIUM,
    "input.type": Level.MEDIUM, "input.hotkey": Level.MEDIUM, "input.press": Level.MEDIUM,
    # screen / vision
    "screen.capture": Level.LOW, "screen.ocr": Level.LOW, "screen.analyze": Level.LOW,
    "screen.locate": Level.LOW,
    # browser
    "browser.open": Level.LOW, "browser.navigate": Level.LOW, "browser.search": Level.LOW,
    "browser.read": Level.LOW, "browser.extract": Level.LOW, "browser.screenshot": Level.LOW,
    "browser.tabs": Level.LOW, "browser.new_tab": Level.LOW, "browser.switch_tab": Level.LOW,
    "browser.back": Level.LOW, "browser.wait": Level.LOW, "browser.state": Level.LOW,
    "browser.close_tab": Level.MEDIUM, "browser.click": Level.MEDIUM,
    "browser.fill": Level.MEDIUM, "browser.select": Level.MEDIUM,
    "browser.press": Level.MEDIUM, "browser.download": Level.MEDIUM,
    "browser.close": Level.MEDIUM,
    "browser.upload": Level.HIGH, "browser.submit": Level.HIGH,
    # files
    "file.list": Level.LOW, "file.read": Level.LOW, "file.exists": Level.LOW,
    "file.stat": Level.LOW, "file.search": Level.LOW,
    "file.write": Level.MEDIUM, "file.create": Level.MEDIUM, "file.mkdir": Level.MEDIUM,
    "file.copy": Level.MEDIUM, "file.move": Level.MEDIUM, "file.rename": Level.MEDIUM,
    "file.delete": Level.HIGH,
    # system / communication / money — always HIGH
    "system.command": Level.HIGH, "system.settings": Level.HIGH, "system.power": Level.HIGH,
    "message.send": Level.HIGH, "purchase": Level.HIGH, "account.change": Level.HIGH,
    # engine-internal
    "task.run": Level.LOW, "engine.status": Level.LOW, "engine.stop": Level.LOW, "wait": Level.LOW,
    "verify": Level.LOW, "workflow.list": Level.LOW, "workflow.save": Level.MEDIUM,
    "workflow.run": Level.MEDIUM, "workflow.delete": Level.MEDIUM,
}

WRITE_ACTIONS = frozenset({
    "file.write", "file.create", "file.mkdir", "file.copy", "file.move", "file.rename",
    "file.delete", "browser.download", "browser.upload", "app.install", "app.uninstall",
})

_PATH_KEYS = ("path", "paths", "src", "source", "dst", "destination", "target_path",
              "folder", "directory", "file", "files", "save_as", "download_dir")

_DESTRUCTIVE_LABEL = re.compile(
    r"\b(delete|remove|erase|wipe|format|uninstall|reset|factory|send|submit|post|publish|"
    r"pay|purchase|buy|checkout|place\s+order|transfer|withdraw|donate|subscribe|"
    r"sign\s*out|log\s*out|deactivate|close\s+account|change\s+password|empty\s+(recycle|trash)|"
    r"permanently|discard|overwrite|install|run\s+as\s+administrator|allow|grant)\b",
    re.I,
)
_SHELL_WINDOW = re.compile(
    r"\b(cmd(\.exe)?|command\s+prompt|powershell|pwsh|terminal|windows\s+terminal|bash|"
    r"wsl|run\b|regedit|registry\s+editor|task\s+scheduler|services)\b", re.I)
_DANGEROUS_HOTKEYS = (
    {"win", "r"}, {"win", "x"}, {"ctrl", "shift", "esc"}, {"ctrl", "alt", "delete"},
    {"ctrl", "alt", "del"}, {"shift", "delete"}, {"shift", "del"}, {"win", "l"},
)
_FINANCIAL_FIELD = re.compile(r"\b(card|cvv|cvc|security code|expir|iban|account number|routing|ssn|"
                              r"social security|passport)\b", re.I)
#: launching by path / URL / protocol / script: the model could run anything
_LAUNCH_BY_PATH = re.compile(r"[\\/:]|\.(bat|cmd|ps1|psm1|vbs|vbe|js|jse|wsf|wsh|hta|msi|msp|lnk|url|scr|com|"
                             r"pif|cpl|reg|jar)$", re.I)
#: built-in Windows programs that run arbitrary code or download files
_LOLBINS = re.compile(r"^(mshta|wscript|cscript|rundll32|regsvr32|certutil|bitsadmin|msbuild|installutil|"
                      r"regasm|regsvcs|cmstp|forfiles|pcalua|schtasks|at|sc|wmic|msiexec|curl|"
                      r"powershell|pwsh|cmd|bash|wsl|ftp)(\.exe)?$", re.I)
_SAFE_SCHEMES = ("http://", "https://", "about:blank")


# ── auth view (fail closed) ─────────────────────────────────────────────────
@dataclass(frozen=True)
class AuthSnapshot:
    privacy_locked: bool
    owner_allowed: bool


def _default_auth() -> AuthSnapshot:
    try:
        from jarvis.core import security
        manager = security.get_auth_manager()
        return AuthSnapshot(privacy_locked=bool(manager.is_privacy_lock_active()),
                            owner_allowed=bool(manager.is_owner_access_allowed()))
    except Exception:
        return AuthSnapshot(privacy_locked=True, owner_allowed=False)


# ── protected paths (owner decision 5) ──────────────────────────────────────
def _windows_system_roots() -> list[Path]:
    roots: list[Path] = []
    for var in ("SYSTEMROOT", "WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)",
                "PROGRAMW6432", "PROGRAMDATA"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value))
    if os.name == "nt":
        drive = os.environ.get("SYSTEMDRIVE", "C:")
        roots += [Path(drive + "\\Windows"), Path(drive + "\\Program Files"),
                  Path(drive + "\\Program Files (x86)"), Path(drive + "\\ProgramData"),
                  Path(drive + "\\$Recycle.Bin"), Path(drive + "\\System Volume Information")]
    return roots


def _norm(path: Path) -> str:
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        resolved = Path(os.path.abspath(str(path)))
    return os.path.normcase(str(resolved))


def protected_path_reason(path: Any, *, write: bool) -> str:
    """Why ``path`` needs the owner's approval, or '' when it is default-allow."""
    text = str(path or "").strip()
    if not text:
        return ""
    if "\x00" in text:
        return "the path contains a NUL byte"
    try:
        from jarvis.core import path_guard
        reason = path_guard.protected_reason(text, write=write)
    except Exception:
        reason = "the path could not be checked"
    if reason or not write:
        return reason or ""
    target = _norm(Path(text))
    for root in _windows_system_roots():
        root_s = _norm(root)
        if target == root_s or target.startswith(root_s.rstrip("\\/") + os.sep):
            return "it is a Windows system directory"
    return ""


def _iter_paths(params: Mapping[str, Any]) -> Iterable[str]:
    for key in _PATH_KEYS:
        value = params.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                if item:
                    yield str(item)
        elif value:
            yield str(value)


def _hotkey_set(params: Mapping[str, Any]) -> set[str]:
    raw = params.get("keys") or params.get("hotkey") or params.get("key") or ""
    if isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = re.split(r"[+\s,]+", str(raw))
    alias = {"windows": "win", "super": "win", "meta": "win", "cmd": "win",
             "control": "ctrl", "escape": "esc", "del": "delete"}
    return {alias.get(p.strip().lower(), p.strip().lower()) for p in parts if p.strip()}


# ── the decision ────────────────────────────────────────────────────────────
@dataclass
class PolicyDecision:
    action: str
    level: Level
    allowed: bool                    # may proceed (possibly after approval)
    needs_approval: bool
    reason: str
    escalations: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return not self.allowed


@dataclass
class ActionPolicy:
    """Classify and gate one action. Pure apart from the injected auth view."""

    auth: Callable[[], AuthSnapshot] = _default_auth
    #: Levels that run without asking. HIGH is never in here.
    auto_levels: frozenset = frozenset({Level.LOW, Level.MEDIUM})

    def classify(self, action: str, params: Mapping[str, Any] | None = None, *,
                 tainted: bool = False) -> tuple[Level, list[str]]:
        params = dict(params or {})
        name = str(action or "").strip().lower()
        reasons: list[str] = []
        level = BASE_LEVELS.get(name)
        if level is None:
            level = Level.HIGH
            reasons.append(f"unknown action '{name}' is treated as high risk")
        requested = Level.parse(params.get("requested_level"))
        if requested and requested.order > level.order:
            level = requested
            reasons.append("the plan marked this step as higher risk")

        write = name in WRITE_ACTIONS
        for path in _iter_paths(params):
            why = protected_path_reason(path, write=write)
            if why:
                level = Level.HIGH
                reasons.append(f"'{Path(path).name or path}' is protected: {why}")

        label = " ".join(str(params.get(k) or "") for k in (
            "target", "name", "label", "title", "text_label", "control", "button", "selector", "path"))
        if name in ("element.click", "element.invoke", "input.click", "input.double_click",
                    "browser.click", "dialog.respond", "menu.select", "browser.press") \
                and _DESTRUCTIVE_LABEL.search(label):
            level = Level.HIGH
            reasons.append("the control looks destructive or outward-facing "
                           f"('{_DESTRUCTIVE_LABEL.search(label).group(0)}')")

        if name in ("input.type", "element.set_text", "input.press", "input.hotkey"):
            window = " ".join(str(params.get(k) or "") for k in ("window", "app", "target_app"))
            if _SHELL_WINDOW.search(window):
                level = Level.HIGH
                reasons.append("typing or pressing keys in a command shell or system tool")
        if name in ("input.hotkey", "input.press"):
            keys = _hotkey_set(params)
            if any(combo <= keys for combo in _DANGEROUS_HOTKEYS):
                level = Level.HIGH
                reasons.append("the shortcut opens a system tool or bypasses the recycle bin")

        if params.get("_private_destination"):
            level = Level.HIGH
            reasons.append(f"local or private address ({params.get('_private_destination')})")
        if params.get("sensitive_form") and name in ("browser.click", "browser.press", "browser.submit"):
            level = Level.HIGH
            reasons.append("submits a form with password or payment fields")
        if name == "browser.fill" and _FINANCIAL_FIELD.search(str(params.get("label") or "")):
            level = Level.HIGH
            reasons.append("types into a payment or identity field")

        url = str(params.get("url") or "").strip().lower()
        if url and name.startswith("browser.") and not url.startswith(_SAFE_SCHEMES):
            level = Level.HIGH
            reasons.append("only http(s) addresses open without approval")

        if name == "app.launch":
            raw = str(params.get("name") or params.get("path") or "").strip()
            target = " ".join(str(params.get(k) or "") for k in ("name", "path", "args"))
            if _LAUNCH_BY_PATH.search(raw) or _LOLBINS.search(raw):
                level = Level.HIGH
                reasons.append("launching a program by path, URL, protocol, script or system binary")
            if _SHELL_WINDOW.search(target) or re.search(r"\b(setup|install|msiexec)\b", target, re.I):
                level = Level.HIGH
                reasons.append("launching a shell or an installer")
            if params.get("args") and level is Level.LOW:
                level = Level.MEDIUM
                reasons.append("launch arguments change what the program does")

        if tainted and level is not Level.HIGH:
            level = level.raised()
            reasons.append("arguments came from untrusted content")
        return level, reasons

    def decide(self, action: str, params: Mapping[str, Any] | None = None, *,
               origin: Origin | str = Origin.OWNER, tainted: bool = False) -> PolicyDecision:
        name = str(action or "").strip().lower()
        level, reasons = self.classify(name, params, tainted=tainted)
        try:
            origin = Origin(getattr(origin, "value", origin))
        except ValueError:
            origin = Origin.UNTRUSTED
            reasons.append("unknown request origin is treated as untrusted")

        snapshot = self.auth()
        if snapshot.privacy_locked:
            return PolicyDecision(name, level, False, False,
                                  "Privacy Lock is active; computer control is blocked.", reasons)
        if not snapshot.owner_allowed:
            return PolicyDecision(name, level, False, False,
                                  "Owner verification is required for computer control.", reasons)
        if origin is Origin.UNTRUSTED and level is not Level.LOW:
            return PolicyDecision(
                name, level, False, False,
                "Refused: this action was requested by content (a page, screenshot, document "
                "or tool output), not by the owner.", reasons)
        needs_approval = level not in self.auto_levels
        reason = "; ".join(reasons) if reasons else f"{level.value}-risk action"
        return PolicyDecision(name, level, True, needs_approval, reason, reasons)
