"""Menus and the command palette, as data.

One list of commands feeds the left hover menu, the right control menu and
the Ctrl+K palette, so the three can never disagree about what exists or what
it is called. Each command has an id that MainWindow maps to an action; the
palette ranks commands with :func:`search`.

No Qt.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    section: str
    keywords: str = ""
    shortcut: str = ""


# Left hover menu: where to go and what to open.
LEFT_SECTIONS = ("Home", "AI Tools", "Media", "Productivity", "Automation", "History", "Workspaces")
# Right control menu: how JARVIS itself behaves.
RIGHT_SECTION = "Controls"

COMMANDS: tuple[Command, ...] = (
    Command("home", "Show the hologram", "Home", "home face stage clear minimise all windows"),
    Command("tile", "Tile windows", "Home", "arrange tidy organise windows"),
    Command("ask", "Ask JARVIS", "AI Tools", "chat type question command bar input", "Ctrl+L"),
    Command("palette", "Command palette", "AI Tools", "search commands", "Ctrl+K"),
    Command("bento", "Bento dashboard", "AI Tools", "dashboard overview cards"),
    Command("open:youtube_music", "YouTube Music", "Media", "music songs player yt"),
    Command("open:music", "Music player", "Media", "songs audio"),
    Command("open:video", "Video player", "Media", "youtube movie watch"),
    Command("open:image", "Image viewer", "Media", "photo picture gallery"),
    Command("open:timer", "Timer", "Productivity", "countdown pomodoro stopwatch"),
    Command("open:news", "News", "Productivity", "headlines articles"),
    Command("open:downloads", "Downloads", "Productivity", "files folder recent"),
    Command("ask:routines", "My routines", "Automation", "rules triggers automations"),
    Command("ask:jobs", "Background jobs", "Automation", "tasks running work"),
    Command("ask:recent_actions", "Recent actions", "History", "log history audit what did you do"),
    Command("activity", "Activity log", "History", "log feed panel"),
    Command("ws:save", "Save workspace…", "Workspaces", "layout snapshot store"),
    Command("ws:load", "Load workspace…", "Workspaces", "layout restore open"),
    Command("mode:jarvis", "JARVIS Mode", RIGHT_SECTION, "persona cyan"),
    Command("mode:bihansa", "BIHANSA Mode", RIGHT_SECTION, "persona pink"),
    Command("settings", "Settings", RIGHT_SECTION, "preferences options configure"),
    Command("system", "System Controls", RIGHT_SECTION, "cpu memory status system"),
    Command("activity_panel", "Activity", RIGHT_SECTION, "feed actions panel"),
    Command("telemetry", "Telemetry", RIGHT_SECTION, "metrics cpu gpu network"),
    # Palette only.
    Command("perf:auto", "Performance: Auto", "Performance", "speed fps tier quality"),
    Command("perf:full", "Performance: Full", "Performance", "speed fps tier quality high"),
    Command("perf:balanced", "Performance: Balanced", "Performance", "speed fps tier quality medium"),
    Command("perf:lite", "Performance: Lite", "Performance", "speed fps tier quality low battery"),
)

# What the "ask:" commands say to JARVIS.
ASK_TEXT = {
    "ask:routines": "show my routines",
    "ask:jobs": "list my background jobs",
    "ask:recent_actions": "show recent actions",
}


def by_section(section: str) -> list[Command]:
    return [c for c in COMMANDS if c.section == section]


def get(command_id: str) -> Command | None:
    for c in COMMANDS:
        if c.id == command_id:
            return c
    return None


def _subsequence_score(query: str, text: str) -> float:
    """How well ``query`` matches ``text`` as an in-order subsequence: 0 for no
    match; more for contiguous runs and matches at word starts."""
    if not query:
        return 1.0
    score, qi, run, prev = 0.0, 0, 0, " "
    for ch in text:
        if qi < len(query) and ch == query[qi]:
            run += 1
            score += 1.0 + run * 0.5 + (2.0 if prev in " -_:/" else 0.0)
            qi += 1
        else:
            run = 0
        prev = ch
    return score if qi == len(query) else 0.0


def search(query: str, extra: list[Command] | None = None, limit: int = 12) -> list[Command]:
    """Commands ranked for the palette. Titles count more than keywords."""
    q = " ".join(str(query or "").lower().split())
    pool = list(COMMANDS) + list(extra or [])
    if not q:
        return pool[:limit]
    ranked = []
    for i, c in enumerate(pool):
        title = c.title.lower()
        s = _subsequence_score(q, title) * 2.0
        if title.startswith(q):
            s += 20.0
        s = max(s, _subsequence_score(q, f"{c.section} {c.keywords}".lower()))
        if s > 0:
            ranked.append((-s, i, c))
    ranked.sort()
    return [c for _s, _i, c in ranked[:limit]]
