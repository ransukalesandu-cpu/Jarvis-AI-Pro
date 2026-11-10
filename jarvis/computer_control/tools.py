"""All computer-control tools, declared once as :class:`contract.ToolSpec`.

``build_registry()`` is what ``jarvis/actions/computer_control_engine.py`` turns
into ``TOOLS`` for the existing action registry. Each project adds its specs in
one ``_register_*`` function; nothing else in the app has to change.
"""
from __future__ import annotations

from jarvis.computer_control import estop, flags
from jarvis.computer_control.contract import SpecRegistry, ToolSpec
from jarvis.computer_control.runner import ActionContext, ActionOutcome


def _status(ctx: ActionContext) -> ActionOutcome:
    """Engine state and per-part readiness. Works while the engine is off or in dry-run
    (that is when the owner most needs it), but only for the verified owner."""
    from jarvis.computer_control import readiness
    from jarvis.computer_control.runner import get_runner

    # The same owner / Privacy Lock view the runner's policy uses for every action.
    auth = get_runner().policy.auth()
    if auth.privacy_locked:
        raise PermissionError("Privacy Lock is active. Computer-control status is hidden.")
    if not auth.owner_allowed:
        raise PermissionError("Owner verification is required to see computer-control status.")
    stop = estop.get()
    last = stop.last
    checks = readiness.report()
    data = {"enabled": flags.enabled(), "dry_run": flags.dry_run(), "source": flags.source(),
            "saved_setting": flags.saved_setting(),
            "stop_engaged": stop.engaged, "stop_generation": stop.generation,
            "last_stop": last.reason if last else "",
            "checks": [check.as_dict() for check in checks]}
    return ActionOutcome(True, readiness.summary(checks), data=data)


def _stop(ctx: ActionContext) -> ActionOutcome:
    event = estop.trigger(str(ctx.params.get("reason") or "requested by the owner"),
                          source="tool")
    return ActionOutcome(True, "Stopped every running computer-control action.",
                         data={"generation": event.generation}, verified=True,
                         evidence="stop generation advanced")


def _register_engine(reg: SpecRegistry) -> None:
    reg.register(ToolSpec(
        id="cc_engine_status", action="engine.status",
        description=("Computer control status: whether the engine is on (and why not), dry-run, "
                     "and which parts are ready on this computer (Windows apps, browser, OCR, "
                     "hosted vision, approval prompt, emergency stop). Use when the owner asks "
                     "whether or why JARVIS can or cannot control the computer. Read-only; "
                     "to turn it on or off use jarvis_settings with setting=computer_control."),
        handler=_status, timeout=10.0, bypass_runner=True, always_available=True))
    reg.register(ToolSpec(
        id="cc_emergency_stop", action="engine.stop",
        description="Emergency stop: immediately stop every running computer-control action.",
        input_schema={"type": "OBJECT", "properties": {
            "reason": {"type": "STRING", "description": "Why (optional)."}}},
        handler=_stop, timeout=5.0, bypass_runner=True))


def _register_windows(reg: SpecRegistry) -> None:
    from jarvis.computer_control.windows import tools as windows_tools
    windows_tools.register(reg)


def _register_browser(reg: SpecRegistry) -> None:
    from jarvis.computer_control.browser import tools as browser_tools
    browser_tools.register(reg)


def _register_visual(reg: SpecRegistry) -> None:
    from jarvis.computer_control.visual import tools as visual_tools
    visual_tools.register(reg)


def _register_files(reg: SpecRegistry) -> None:
    from jarvis.computer_control import files
    files.register(reg)


def _register_orchestrator(reg: SpecRegistry) -> None:
    from jarvis.computer_control.orchestrator import jobs
    jobs.register(reg)


def _register_workflows(reg: SpecRegistry) -> None:
    from jarvis.computer_control.workflows import tools as workflow_tools
    workflow_tools.register(reg)


_REGISTRARS = [_register_engine, _register_windows, _register_browser, _register_visual, _register_files, _register_orchestrator, _register_workflows]


def build_registry() -> SpecRegistry:
    reg = SpecRegistry()
    for register in _REGISTRARS:
        register(reg)
    return reg
