"""Voice glue: command parsing and throttled spoken progress.

Two small, testable pieces — no microphone, no TTS, no event loop:

* :class:`VoiceCommandRouter` recognises the handful of phrasings that must work
  even when the model is unreachable (stop / pause / resume / status / report),
  and decides when a sentence is an autonomous-work *objective*. It is
  deliberately conservative: the primary path is still the Gemini Live tool
  call, this only catches the cases where waiting for a round trip would be
  wrong — above all "JARVIS, stop."
* :class:`SpeechAnnouncer` turns :class:`~agent.events.AgentEvent` milestones
  into at most one sentence every few seconds. Progress chatter is the fastest
  way to make a useful agent unbearable, so step-level events are silent and
  only plan/blocker/completion/error events speak.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from agent.events import AgentEvent
from agent.models import TaskState
from agent.presentation import state_label

_WORK_VERBS = {
    "inspect", "fix", "repair", "implement", "upgrade", "refactor", "build",
    "finish", "debug", "test", "tests", "run", "review", "audit", "install",
    "update", "analyse", "analyze", "migrate", "add", "remove", "clean",
}


@dataclass(frozen=True)
class VoiceCommand:
    action: str                       # run | stop | pause | resume | status | report
    objective: str = ""
    criteria: list[str] = field(default_factory=list)


class VoiceCommandRouter:
    """Match a spoken sentence to an agent control action."""

    _WAKE = r"^\s*(?:hey\s+|ok\s+|okay\s+)?jarvis[\s,.:;-]*"

    def __init__(self) -> None:
        self._stop = re.compile(
            r"^(?:stop|halt|abort|cancel)(?:\s+(?:the\s+|your\s+|this\s+|all\s+)?"
            r"(?:task|tasks|work|working|everything|automation|autonomy|it))?$"
            r"|^(?:jarvis,?\s+)?stop\s+(?:the\s+)?task",
            re.IGNORECASE,
        )
        self._pause = re.compile(
            r"^(?:pause|hold on|hold that|wait a (?:moment|second|minute)|"
            r"pause (?:the |your |this )?task|take a break)$",
            re.IGNORECASE,
        )
        self._resume = re.compile(
            r"^(?:resume|continue|carry on|keep going|go on|unpause|"
            r"resume (?:the |your |this )?task|continue (?:the |your |this )?task)$",
            re.IGNORECASE,
        )
        self._status = re.compile(
            r"^(?:status|task status|what are you doing|what is your status|"
            r"how(?:'s| is) (?:the )?task(?: going)?|progress|any progress|"
            r"are you still working)$",
            re.IGNORECASE,
        )
        self._report = re.compile(
            r"^(?:report|task report|what did you find|what did you change|"
            r"what happened with the task|summary of the task|final report)$",
            re.IGNORECASE,
        )

    def parse(self, text: str) -> VoiceCommand | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        stripped = re.sub(self._WAKE, "", raw, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"[.!?]+$", "", stripped).strip()
        lowered = candidate.casefold()

        if self._stop.search(lowered):
            return VoiceCommand("stop")
        if self._pause.search(lowered):
            return VoiceCommand("pause")
        if self._resume.search(lowered):
            return VoiceCommand("resume")
        if self._status.search(lowered):
            return VoiceCommand("status")
        if self._report.search(lowered):
            return VoiceCommand("report")

        if self.looks_like_objective(candidate):
            return VoiceCommand("run", objective=candidate,
                                criteria=self.extract_criteria(candidate))
        return None

    @staticmethod
    def looks_like_objective(text: str) -> bool:
        """True for a multi-action engineering instruction, not small talk."""
        lowered = str(text or "").casefold()
        if len(lowered.split()) < 5:
            return False
        verbs = {verb for verb in _WORK_VERBS if re.search(rf"\b{verb}\b", lowered)}
        if len(verbs) >= 2:
            return True
        if "until" in lowered and ("complete" in lowered or "done" in lowered) and verbs:
            return True
        return False

    @staticmethod
    def extract_criteria(text: str) -> list[str]:
        """Pull explicit completion criteria out of "until ..." clauses."""
        lowered = str(text or "")
        criteria: list[str] = []
        match = re.search(r"until\s+(.+?)(?:[.;]|$)", lowered, re.IGNORECASE)
        if match:
            criteria.append(match.group(1).strip().capitalize())
        if "all relevant tests" in lowered.casefold() or "run all" in lowered.casefold():
            criteria.append("All relevant tests pass.")
        return criteria[:3]


class SpeechAnnouncer:
    """Speak important agent events, never more than one every N seconds."""

    _SPOKEN_KINDS = {"planned", "blocked", "finished", "paused", "resumed", "started"}

    def __init__(
        self,
        speak: Callable[[str], None] | None = None,
        *,
        min_interval_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        enabled: bool = True,
    ):
        self._speak = speak
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._clock = clock
        self.enabled = bool(enabled)
        self._last = 0.0
        self._last_text = ""
        self.spoken: list[str] = []

    def attach(self, speak: Callable[[str], None]) -> None:
        self._speak = speak

    def announce(self, event: AgentEvent) -> str | None:
        if not self.enabled or self._speak is None:
            return None
        if event.kind not in self._SPOKEN_KINDS:
            return None
        message = self._phrase(event)
        if not message:
            return None
        if self._should_suppress(event, message):
            return None
        return self.say(message)

    def say(self, message: str) -> str | None:
        text = str(message or "").strip()
        if not text or self._speak is None:
            return None
        try:
            self._speak(text)
        except Exception:
            return None
        self._last = self._clock()
        self._last_text = text
        self.spoken.append(text)
        del self.spoken[:-20]
        return text

    def _should_suppress(self, event: AgentEvent, message: str) -> bool:
        if event.kind == "finished":
            return False
        if not self.spoken:
            return False  # the first thing it says is never throttled
        if message == self._last_text:
            return True
        return (self._clock() - self._last) < self.min_interval_s

    @staticmethod
    def _phrase(event: AgentEvent) -> str:
        if event.kind == "finished":
            counts = event.data.get("report", {})
            failed = len(counts.get("failed") or [])
            blocked = len(counts.get("blocked") or [])
            if event.state is TaskState.COMPLETED:
                return "Task complete. Everything I planned finished and verified."
            if event.state is TaskState.CANCELLED:
                return "Task stopped."
            if blocked and not failed:
                reason = (counts.get("blocked") or [["", "needs your approval"]])[0][1]
                return f"I'm blocked: {reason}"
            if failed:
                return f"The task failed on {failed} step{'s' if failed != 1 else ''}."
            return "The task finished."
        if event.kind == "planned":
            steps = event.data.get("plan", {}).get("steps")
            return "I have a plan." if not steps else f"I've split this into {len(steps)} steps."
        if event.kind == "blocked":
            return f"I'm blocked. {event.message}" if event.message else "I'm blocked."
        if event.kind == "paused":
            return "Paused."
        if event.kind == "resumed":
            return "Continuing."
        if event.kind == "started":
            return "Starting the task now."
        return ""


def status_sentence(task: object | None) -> str:
    """One spoken sentence describing the current task."""
    if task is None:
        return "No task is running."
    state = getattr(task, "state", None)
    objective = str(getattr(task, "objective", "") or "")
    head = state_label(state) if state is not None else "IDLE"
    step = getattr(task, "current_step", lambda: None)()
    progress = int(float(getattr(task, "progress", lambda: 0.0)()) * 100)
    if step is not None:
        return (f"{head} — {progress}% done. Current step: {step.title}. "
                f"Objective: {objective[:160]}")
    return f"{head} — {progress}% done. Objective: {objective[:160]}"
