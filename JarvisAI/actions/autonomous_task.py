"""Voice tool: start, steer and report long-running autonomous work.

This is the bridge between the Gemini Live tool call and
:class:`agent.integration.AgentService`. It never blocks: ``run`` starts the
background worker and returns immediately with a sentence the model can say, so
the conversation stays responsive while the task continues.

Security is enforced in three places and none of them is optional:

1. ``core.dispatcher``/``core.security`` tier this tool as SENSITIVE for
   steering and DANGEROUS for ``run`` (see ``_TIERS`` in core/security.py).
2. ``AgentService.start`` refuses unless the owner is authenticated, Privacy
   Lock is off and autonomy is enabled.
3. Each planned step is classified again by ``agent.policy``; anything
   consequential additionally needs the existing ``core.confirm`` approval.

A single "stop" (voice, HUD button, or the Dynamic Island) sets the runner's
cancellation event, which is checked before every action and inside running
commands.
"""
from __future__ import annotations

from agent.integration import get_service


def autonomous_task(action: str = "status", objective: str = "", criteria=None,
                     speak=None, **_ignored) -> str:
    """Run `action` against the autonomous task engine and return a spoken reply."""
    service = get_service()
    return service.handle_tool(
        {"action": str(action or "status"), "objective": objective,
         "criteria": criteria or []},
        speak=speak,
    )


TOOL = {
    "name": "autonomous_task",
    "description": (
        "Start and steer a long-running autonomous engineering task that plans, "
        "acts, observes, verifies and recovers without asking again after every "
        "step. Use action=run with a clear multi-step objective (for example "
        "inspect the project, fix the failing tests, run all relevant tests and "
        "report) when the owner asks for sustained work. Use status/pause/resume/"
        "stop/report for the running task. Starting requires verified owner "
        "access; consequential steps still ask for approval. Never claim a task "
        "finished until its report says so."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["run", "status", "pause", "resume", "stop", "report", "pending"],
                "description": "Start a task, steer it, or read its state.",
            },
            "objective": {
                "type": "STRING",
                "description": (
                    "The complete objective for action=run, phrased as one "
                    "instruction. Include what 'done' means when the owner said it."
                ),
            },
            "criteria": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Optional explicit completion criteria.",
            },
        },
        "required": ["action"],
    },
    "handler": autonomous_task,
    # The worker runs on its own thread; the model should not wait for it.
    "behavior": "NON_BLOCKING",
    "scheduling": "SILENT",
}
