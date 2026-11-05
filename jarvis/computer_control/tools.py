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
    stop = estop.get()
    last = stop.last
    data = {"enabled": flags.enabled(), "dry_run": flags.dry_run(),
            "stop_engaged": stop.engaged, "stop_generation": stop.generation,
            "last_stop": last.reason if last else ""}
    return ActionOutcome(True, flags.describe(), data=data)


def _stop(ctx: ActionContext) -> ActionOutcome:
    event = estop.trigger(str(ctx.params.get("reason") or "requested by the owner"),
                          source="tool")
    return ActionOutcome(True, "Stopped every running computer-control action.",
                         data={"generation": event.generation}, verified=True,
                         evidence="stop generation advanced")


def _register_engine(reg: SpecRegistry) -> None:
    reg.register(ToolSpec(
        id="cc_engine_status", action="engine.status",
        description="Computer control engine status: whether it is on, dry-run mode, and the emergency stop.",
        handler=_status, timeout=5.0))
    reg.register(ToolSpec(
        id="cc_emergency_stop", action="engine.stop",
        description="Emergency stop: immediately stop every running computer-control action.",
        input_schema={"type": "OBJECT", "properties": {
            "reason": {"type": "STRING", "description": "Why (optional)."}}},
        handler=_stop, timeout=5.0, bypass_runner=True))


def _register_windows(reg: SpecRegistry) -> None:
    from jarvis.computer_control.windows import tools as windows_tools
    windows_tools.register(reg)


_REGISTRARS = [_register_engine, _register_windows]


def build_registry() -> SpecRegistry:
    reg = SpecRegistry()
    for register in _REGISTRARS:
        register(reg)
    return reg
