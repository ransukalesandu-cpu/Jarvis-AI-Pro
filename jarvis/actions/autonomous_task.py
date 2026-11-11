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

A single "stop" ("Jarvis, stop" via core/runtime/live_tools._stop_everything,
the HUD button, the Dynamic Island, or Cancel in the job list) sets the runner's
cancellation event, which is checked before every action and inside running
commands.
"""
from __future__ import annotations

from jarvis.agent.integration import get_service


_FIELDS = ("action", "objective", "criteria", "task_id", "name", "workflow_id")


def autonomous_task(parameters: dict | None = None, *, speak=None, dispatch=None,
                    **fields) -> str:
    """Run the requested action against the autonomous task engine; return a spoken reply.

    The action registry calls every handler as ``handler(parameters=<model args>, ...)``
    (core/action_loader._call_handler), so the model's arguments arrive in
    ``parameters``. Keyword fields are still accepted for direct callers; the
    registry's dict wins when both are given.
    """
    args = {key: fields[key] for key in _FIELDS if key in fields}
    if isinstance(parameters, dict):
        args.update({key: parameters[key] for key in _FIELDS if key in parameters})
    service = get_service()
    if dispatch is not None:
        # Lets planned `registry_call` steps run local tools through the same
        # registry layer as a spoken call (only used when registry planning is on).
        service.attach_tool_dispatch(dispatch)
    return service.handle_tool(
        {"action": str(args.get("action") or "status"),
         "objective": str(args.get("objective") or ""),
         "criteria": args.get("criteria") or [],
         "task_id": str(args.get("task_id") or ""),
         "name": str(args.get("name") or ""),
         "workflow_id": str(args.get("workflow_id") or "")},
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
                "enum": [
                    "run", "status", "pause", "resume", "stop", "report", "pending",
                    "save_workflow", "list_workflows", "suggest_workflows", "run_workflow",
                ],
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
            "task_id": {
                "type": "STRING",
                "description": "Completed task ID for action=save_workflow.",
            },
            "name": {
                "type": "STRING",
                "description": "User-approved workflow name for action=save_workflow.",
            },
            "workflow_id": {
                "type": "STRING",
                "description": "Saved workflow ID for action=run_workflow.",
            },
        },
        "required": ["action"],
    },
    "handler": autonomous_task,
    # The worker runs on its own thread; the model should not wait for it.
    "behavior": "NON_BLOCKING",
    "scheduling": "SILENT",
}
