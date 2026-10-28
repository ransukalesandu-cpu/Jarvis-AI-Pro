"""JARVIS autonomous task engine.

This package implements the observe→plan→act→verify→recover loop that lets
JARVIS carry a multi-step objective to completion from a single instruction,
while reusing the application's existing security, voice and UI layers.

Design rules (all enforced by tests in ``JarvisAI/tests/test_agent_*.py``):

* **No Qt, no audio, no global side effects at import time.** The package is
  importable in a headless CI container and in the running app.
* **Explicit dependencies.** Screen capture, vision, input control, sleep and
  clocks are injected, so every failure path can be exercised without a
  display, a microphone, an API key or a real desktop.
* **Bounded everything.** Steps, attempts, runtime, output size, queue depth
  and retry backoff all have hard limits.
* **Fail closed.** A consequential action needs authorization from the existing
  security layer and a human approval; the engine never assumes consent.

Importing the public helpers is cheap; heavy optional dependencies (mss, PIL,
pyautogui, google-genai, openai, pytesseract) are imported lazily by the module
that actually needs them.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_AGENT_DIR",
    "Task",
    "TaskReport",
    "TaskRunner",
    "TaskState",
    "TaskStep",
    "StepKind",
    "StepState",
    "agent_data_dir",
]

from agent.models import (
    StepKind,
    StepState,
    Task,
    TaskReport,
    TaskState,
    TaskStep,
)
from agent.store import DEFAULT_AGENT_DIR, agent_data_dir


def __getattr__(name: str):
    """Import the runner lazily so ``import agent`` never pulls subprocess code."""
    if name == "TaskRunner":
        from agent.runner import TaskRunner

        return TaskRunner
    raise AttributeError(f"module 'agent' has no attribute {name!r}")
