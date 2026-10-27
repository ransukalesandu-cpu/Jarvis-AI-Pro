"""Explicit, local voice-command parsing for JARVIS UI controls.

This module intentionally does not execute actions or import Qt. Callers must
apply owner-authentication and confirmation policy before dispatching a parsed
command to the visible interface.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceUICommand:
    """A narrowly parsed request to operate a visible UI control."""

    action: str
    target: str = ""
    raw_text: str = ""
    # "on" / "off" requests are state-aware, not blind clicks.
    desired_state: str = ""


_CONFIRMATION_PHRASES = {
    "confirm",
    "confirm action",
    "approve",
    "approve action",
    "accept access",
    "allow access",
    "approve access",
    "grant access",
    "accept request",
    "approve request",
    "allow request",
    "cancel",
    "cancel action",
    "deny",
    "deny action",
    "deny access",
    "reject access",
    "decline access",
    "deny request",
    "reject request",
    "decline request",
}

# These labels indicate actions that must not be triggered by a generic
# "click <button>" voice command. They must go through the application's
# dedicated action flow (including its confirmation gate, where applicable).
_HIGH_IMPACT_TERMS = (
    "delete", "remove", "purge", "erase", "wipe",
    "shutdown", "shut down", "power off", "restart", "reboot",
    "factory reset", "reset all", "reset memory", "reset settings",
    "clear all", "clear memory", "clear history", "clear conversation",
    "delete history", "erase history", "purge memory", "delete memory", "erase memory",
    "memory import", "memory export", "import memory", "export memory",
    "publish", "post now", "send message", "send email", "send reply",
    "make call", "call now", "phone call", "purchase", "buy now",
    "transfer money", "withdraw money", "dev agent",
    "execute code", "execute script", "run script",
)


def normalize_label(value: str) -> str:
    """Normalize spoken text and widget labels for safe, predictable matching."""
    text = str(value or "").casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def is_high_impact_ui_label(value: str) -> bool:
    """Return True when a UI label describes a high-impact/destructive action."""
    label = normalize_label(value)
    if not label:
        return False
    return any(
        re.search(rf"\b{re.escape(normalize_label(term))}\b", label)
        for term in _HIGH_IMPACT_TERMS
    )


def parse_voice_ui_command(text: str) -> VoiceUICommand | None:
    """Parse only clear, explicit UI commands; ordinary conversation returns None.

    Protected confirmation phrases are deliberately left to core.confirm, which
    verifies the pending request and the live speaker before it can approve it.
    """
    raw = str(text or "").strip()
    phrase = normalize_label(raw)
    if not phrase:
        return None

    # Remove the optional wake-name prefix and polite lead-ins, but do not try to
    # infer clicks from free-form conversational requests.
    phrase = re.sub(r"^(?:hey\s+)?(?:jarvis|maya)\s+", "", phrase)
    phrase = re.sub(
        r"^(?:(?:please|kindly)\s+|(?:can|could|would)\s+you\s+)+",
        "",
        phrase,
    ).strip()

    if phrase in _CONFIRMATION_PHRASES or phrase in {"yes", "no", "okay", "ok"}:
        return None

    if phrase in {"scroll up", "scroll down", "scroll top", "scroll bottom"}:
        return VoiceUICommand("scroll", phrase.split()[-1], raw)
    if phrase in {"focus next", "focus previous", "focus prev"}:
        return VoiceUICommand("focus_next" if phrase.endswith("next") else "focus_previous", "", raw)
    if phrase in {"next tab", "previous tab", "prev tab"}:
        return VoiceUICommand("next_tab" if phrase.startswith("next") else "previous_tab", "", raw)
    if phrase in {"go back", "go to previous"}:
        return VoiceUICommand("click", "back", raw)
    if phrase in {"close dialog", "close window", "close panel", "close overlay",
                  "dismiss dialog", "dismiss window", "dismiss panel"}:
        return VoiceUICommand("close_active", "", raw)

    match = re.fullmatch(
        r"(?:go|navigate|switch)\s+to\s+(.+)",
        phrase,
    )
    if match:
        target = _clean_target(match.group(1))
        return VoiceUICommand("click", target, raw) if target else None

    # Singlish suffix forms, common in spoken Sinhala-English commands:
    # "settings eka open karanna", "settings button eka click karanna".
    match = re.fullmatch(
        r"(.+?)\s+(?:(?:eka|the)\s+)?"
        r"(open|show|click|press|tap|select|toggle|close|dismiss)\s+karanna",
        phrase,
    )
    if match:
        target = _clean_target(match.group(1))
        verb = match.group(2)
        if verb in {"close", "dismiss"} and target in {
            "dialog", "window", "panel", "overlay", "active dialog",
            "active window", "active panel", "active overlay",
        }:
            return VoiceUICommand("close_active", "", raw)
        return VoiceUICommand("click", target, raw) if target else None

    match = re.fullmatch(
        r"(open|show|click|press|tap|select|toggle|close|dismiss)\s+karanna\s+(.+)",
        phrase,
    )
    if match:
        verb, target = match.group(1), _clean_target(match.group(2))
        if verb in {"close", "dismiss"} and target in {
            "dialog", "window", "panel", "overlay", "active dialog",
            "active window", "active panel", "active overlay",
        }:
            return VoiceUICommand("close_active", "", raw)
        return VoiceUICommand("click", target, raw) if target else None

    # For "turn on microphone", "mute microphone", etc. the UI still chooses
    # the visible control; the parser never performs an OS-level operation.
    match = re.fullmatch(
        r"(?:turn|switch)\s+(on|off)\s+(?:the\s+)?(.+)",
        phrase,
    )
    if match:
        desired_state = match.group(1)
        target = _clean_target(match.group(2))
        return (
            VoiceUICommand("set_state", target, raw, desired_state)
            if target else None
        )

    match = re.fullmatch(
        r"(mute|unmute|enable|disable)\s+(?:the\s+)?(.+)",
        phrase,
    )
    if match:
        verb, target = match.group(1), _clean_target(match.group(2))
        desired_state = "off" if verb in {"mute", "disable"} else "on"
        return (
            VoiceUICommand("set_state", target, raw, desired_state)
            if target else None
        )

    match = re.fullmatch(
        r"(click|press|tap|activate|choose|select|open|show|toggle|close|dismiss)"
        r"\s+(?:(?:on|the)\s+)*(?:(?:button|control|tab|menu|panel|option)\s+)?(.+)",
        phrase,
    )
    if not match:
        return None

    verb, target = match.group(1), _clean_target(match.group(2))
    if not target:
        return None
    if verb in {"close", "dismiss"} and target in {
        "dialog", "window", "panel", "overlay", "active dialog", "active window",
        "active panel", "active overlay",
    }:
        return VoiceUICommand("close_active", "", raw)
    if len(target) > 100:
        return None
    return VoiceUICommand("click", target, raw)


def _clean_target(value: str) -> str:
    target = normalize_label(value)
    target = re.sub(r"^(?:the|a|an)\s+", "", target)
    target = re.sub(r"\s+eka$", "", target)
    target = re.sub(r"\s+(?:button|control|tab|menu|panel|option)$", "", target)
    return target.strip()
