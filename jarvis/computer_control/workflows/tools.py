"""The ``cc_workflow`` ToolSpec: list / show / save_last / run / delete."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.runner import ActionContext, ActionOutcome
from jarvis.computer_control.workflows.library import LocalStore, WorkflowError, cloud_sync, draft_from_report
from jarvis.computer_control.workflows.runner import run_workflow, validate

OPS = {"list": "workflow.list", "show": "workflow.list", "validate": "workflow.list",
       "save_last": "workflow.save", "run": "workflow.run", "delete": "workflow.delete"}

_store: Optional[LocalStore] = None


def get_store() -> LocalStore:
    global _store
    if _store is None:
        _store = LocalStore()
    return _store


def set_store(store: Optional[LocalStore]) -> None:
    global _store
    _store = store


def _action_for(params: Mapping[str, Any]) -> str:
    return OPS.get(str(params.get("op") or "list").strip().lower(), "unknown")


def _enrich(params: dict) -> dict:
    """Saving always needs the owner; running an untrusted workflow does too."""
    op = str(params.get("op") or "").lower()
    if op == "save_last":
        params["requested_level"] = "high"
    if op == "run":
        wf = get_store().get(str(params.get("name") or ""))
        if wf is None or not wf.trusted:
            params["requested_level"] = "high"
    return params


def register(reg: SpecRegistry) -> None:
    def handler(ctx: ActionContext) -> ActionOutcome:
        p, store = ctx.params, get_store()
        op = str(p.get("op") or "list").lower()
        name = str(p.get("name") or "")
        if op == "list":
            items = store.all()
            return ActionOutcome(True, f"{len(items)} workflow(s): " + "; ".join(w.summary() for w in items[:20]),
                                 data={"workflows": [w.as_dict() for w in items]}, verified=True)
        if op in ("show", "validate"):
            wf = store.get(name)
            if wf is None:
                return ActionOutcome(False, f"No workflow called '{name}'.")
            problems = validate(wf, reg, dict(p.get("params") or {})) if op == "validate" else []
            return ActionOutcome(not problems, wf.summary() + (f". Problems: {'; '.join(problems)}" if problems else ""),
                                 data={"workflow": wf.as_dict(), "problems": problems}, verified=not problems)
        if op == "save_last":
            from jarvis.computer_control.orchestrator.jobs import last_report
            report = last_report()
            if report is None:
                return ActionOutcome(False, "There is no finished task to save yet.")
            try:
                draft = draft_from_report(report, name)
            except WorkflowError as exc:
                return ActionOutcome(False, str(exc))
            wf = store.put(draft, new_version=True)
            synced = cloud_sync(wf)
            again = store.get(wf.name)
            return ActionOutcome(True, f"Saved {wf.summary()}" + (" (metadata synced)" if synced else ""),
                                 data={"workflow": wf.as_dict()}, verified=again is not None and
                                 again.version == wf.version, evidence="read back from the store")
        if op == "run":
            wf = store.get(name)
            if wf is None:
                return ActionOutcome(False, f"No workflow called '{name}'.")
            from jarvis.computer_control.orchestrator.jobs import run_detached
            try:
                report = run_detached(ctx, lambda cancel: run_workflow(
                    wf, reg, store, params=dict(p.get("params") or {}), cancel_event=cancel,
                    job_id=ctx.job_id))
            except WorkflowError as exc:
                return ActionOutcome(False, str(exc))
            after = store.get(name)
            return ActionOutcome(report.success, f"{report.summary} Now: {after.summary() if after else ''}",
                                 data={"report": {k: v for k, v in report.as_dict().items() if k != 'trace'}},
                                 verified=report.success and report.steps_verified > 0 or None)
        if op == "delete":
            ok = store.delete(name)
            return ActionOutcome(ok, f"Deleted '{name}'." if ok else f"No workflow called '{name}'.",
                                 verified=ok and store.get(name) is None)
        return ActionOutcome(False, f"Unknown op '{op}'.")

    S = "STRING"
    reg.register(ToolSpec(
        id="cc_workflow", action="workflow.list",
        description=("Saved computer-control workflows: list, show, validate, save_last (save the task that just "
                     "finished; needs the owner's approval), run (replays with verification; untrusted workflows "
                     "need approval until they have 3 verified runs), delete."),
        input_schema={"type": "OBJECT", "properties": {
            "op": {"type": S, "enum": list(OPS)}, "name": {"type": S},
            "params": {"type": S, "description": 'JSON object of run-time values, e.g. {"password": "..."}'}},
            "required": ["op"]},
        handler=_wrap_params(handler), timeout=1800.0, long_running=False, action_for=_action_for,
        enrich=_enrich))


def _wrap_params(fn):
    """``params`` arrives as a JSON string (Gemini cannot take free-form objects)."""
    def inner(ctx: ActionContext) -> ActionOutcome:
        raw = ctx.params.get("params")
        if isinstance(raw, str) and raw.strip():
            from jarvis.core.tool_runtime import json_object_arg
            try:
                ctx.params["params"] = json_object_arg(raw)
            except ValueError:
                return ActionOutcome(False, "params must be a JSON object.")
        return fn(ctx)
    return inner
