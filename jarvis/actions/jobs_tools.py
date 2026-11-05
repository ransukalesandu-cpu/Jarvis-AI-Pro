"""Background jobs by voice: start any tool in the background, check, cancel.

start_job runs a tool as a job and returns at once; JARVIS announces the
result when it finishes (core/jobs.py). Tools marked long_running already
start as jobs on their own.
"""
from __future__ import annotations

from jarvis.core.jobs import get_job_manager
from jarvis.core.tool_runtime import json_object_arg


def start_job(parameters: dict, start_background=None, **_ctx) -> str:
    p = parameters or {}
    tool = str(p.get("tool") or "").strip()
    if not tool:
        return "Which tool should run in the background?"
    if start_background is None:
        return "Background jobs need a live session."
    job_id = start_background(tool, json_object_arg(p.get("args")))
    return f"Started job {job_id} ({tool}). I'll tell you when it is done."


def job_status(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    manager = get_job_manager()
    job_id = str(p.get("job_id") or "").strip()
    if str(p.get("action") or "").lower() == "cancel":
        if job_id.lower() == "all":
            return f"Cancelled {manager.cancel_all()} job(s)."
        return f"Cancelled {job_id}." if manager.cancel(job_id) else f"No running job {job_id}."
    if job_id:
        job = manager.get(job_id)
        return job.summary() if job else f"No job {job_id}."
    jobs = manager.list()[:10]
    return "\n".join(j.summary() for j in jobs) if jobs else "No background jobs."


TOOLS = [
    {
        "name": "start_job",
        "description": "Run any tool in the background (tool + args) so the conversation continues.",
        "parameters": {"type": "OBJECT", "properties": {
            "tool": {"type": "STRING"},
            "args": {"type": "STRING", "description": "JSON object of the tool's arguments"},
        }, "required": ["tool"]},
        "handler": start_job, "risk": "write", "timeout": 15,
    },
    {
        "name": "job_status",
        "description": "Status of background jobs (all, or one job_id); action=cancel stops one or 'all'.",
        "parameters": {"type": "OBJECT", "properties": {
            "job_id": {"type": "STRING"},
            "action": {"type": "STRING", "description": "status | cancel"},
        }},
        "handler": job_status, "risk": "read", "timeout": 10,
    },
]
