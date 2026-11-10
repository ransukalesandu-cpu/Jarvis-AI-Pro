"""Which tool does the model pick? Tool-choice eval for computer-control routing (audit P0-3).

Two parts:

* **Offline** (default, no key, deterministic; also run by the test suite): for each
  mode it builds the tool list and routing prompt exactly as the live session does
  and checks that every case still has at least one acceptable tool on offer —
  so a routing mode can never leave a request with no way to do it.
* **Live** (``--live``, owner-run, needs ``gemini_api_key``): sends each case as a
  typed turn to the real Gemini Live model with that mode's tools and system
  prompt, records the first tool the model calls, and closes the session. **No
  tool is ever executed** — nothing on the computer changes.

Modes: ``off`` (engine off), ``both``, ``prefer_engine``, ``engine_only``.
Offline runs assume Windows and the browser are ready (``--actual-readiness`` uses
this computer's real readiness instead).

    python -m jarvis.eval.tool_choice                  # offline report
    python -m jarvis.eval.tool_choice --live           # all modes, 30 cases each
    python -m jarvis.eval.tool_choice --live --modes both prefer_engine --repeat 2

Results: ``jarvis/eval/results/tool_choice_latest.json`` (git-ignored). Only the
synthetic case texts and tool names are stored — no transcript, no audio, no key.
The system prompt is ``core/prompt.txt`` plus the routing section; the app adds
memory, identity and session rules on top, so live numbers are an approximation
of the full app. Compare modes against each other, not against an absolute bar.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

EVAL_DIR = Path(__file__).resolve().parent
CASES_PATH = EVAL_DIR / "tool_choice_cases.jsonl"
RESULTS_PATH = EVAL_DIR / "results" / "tool_choice_latest.json"
MODES = ("off", "both", "prefer_engine", "engine_only")
ASSUMED_READY = {"windows": True, "browser": True}


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    accept: tuple[str, ...]     # tools that do the job (any mode)
    engine: tuple[str, ...]     # cc_* tools that count as "the engine was chosen"


@dataclass
class Setup:
    mode: str
    declarations: list[dict]
    system_prompt: str
    hidden: frozenset = frozenset()
    offered: frozenset = field(default_factory=frozenset)


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            cases.append(Case(row["id"], row["text"], tuple(row["accept"]), tuple(row["engine"])))
    return cases


@contextlib.contextmanager
def _mode(mode: str) -> Iterator[None]:
    from jarvis.computer_control import flags
    previous = os.environ.get(flags.ENV_ROUTING)
    if mode != "off":
        os.environ[flags.ENV_ROUTING] = mode
    try:
        with flags.override(enabled=mode != "off", dry_run=False):
            yield
    finally:
        if previous is None:
            os.environ.pop(flags.ENV_ROUTING, None)
        else:
            os.environ[flags.ENV_ROUTING] = previous


def _registries():
    import jarvis.main as app
    from jarvis.core.action_loader import discover_actions
    from jarvis.core.plugin_loader import discover_plugins
    base = Path(app.__file__).resolve().parent
    inline = {t["name"] for t in app.TOOL_DECLARATIONS}
    actions = discover_actions(base / "actions", reserved_names=inline, logger=lambda m: None)
    plugins = discover_plugins(plugins_dir=base / "plugins", core_tool_names=inline | actions.names(),
                               logger=lambda m: None, notify=lambda m: None)
    return app, actions, plugins


def build_setup(mode: str, *, ready: dict | None = None, registries=None) -> Setup:
    """Tool list and system prompt for one mode, built like JarvisLive._build_config."""
    from jarvis.computer_control import readiness, routing
    app, actions, plugins = registries or _registries()
    with _mode(mode):
        if ready is None:
            ready = {"windows": readiness.windows_check().ok, "browser": readiness.browser_check().ok}
        hidden = routing.hidden_tools(ready)
        decls = [app.with_device_parameter(d) for d in (
            app.TOOL_DECLARATIONS + actions.get_tool_declarations() + plugins.get_tool_declarations())
            if d.get("name") not in hidden]
        names = {d["name"] for d in decls}
        template = app.PROMPT_PATH.read_text(encoding="utf-8")
        prompt = app._render_prompt(template, {
            "assistant_name": "JARVIS",
            "platform": "Windows 11" if ready.get("windows") else f"{platform.system()} {platform.release()}",
            "capabilities": app._describe_tools(decls),
            "limits": app._describe_limits(has_vision="screen_process" in names, has_mic=True),
        })
        block = routing.prompt_block(names, ready=ready)
    return Setup(mode, decls, prompt + ("\n\n" + block if block else ""), hidden, frozenset(names))


def offline_report(cases: list[Case], modes: Iterable[str] = MODES, *, ready: dict | None = None) -> dict:
    registries = _registries()
    report: dict = {"ready": ready or "actual", "modes": {}}
    for mode in modes:
        setup = build_setup(mode, ready=ready, registries=registries)
        impossible = [c.id for c in cases if not (set(c.accept) | set(c.engine)) & setup.offered]
        report["modes"][mode] = {
            "tools": len(setup.declarations),
            "declaration_bytes": len(json.dumps(setup.declarations, ensure_ascii=False)),
            "system_prompt_chars": len(setup.system_prompt),
            "hidden": sorted(setup.hidden),
            "routing_section": "[COMPUTER CONTROL ROUTING]" in setup.system_prompt,
            "cases_without_an_offered_tool": impossible,
        }
    return report


# ── live ─────────────────────────────────────────────────────────────────────
def score(case: Case, called: list[str]) -> str:
    first = called[0] if called else ""
    if not first:
        return "no_tool"
    if first in case.engine:
        return "engine"
    if first in case.accept:
        return "accepted"
    return "other"


async def _first_tools(client, model: str, setup: Setup, text: str, timeout: float) -> list[str]:
    config = {"response_modalities": ["AUDIO"], "system_instruction": setup.system_prompt,
              "tools": [{"function_declarations": setup.declarations}]}
    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(turns={"role": "user", "parts": [{"text": text}]},
                                          turn_complete=True)

        async def read() -> list[str]:
            async for message in session.receive():
                call = getattr(message, "tool_call", None)
                if call is not None and call.function_calls:
                    # Recorded, never executed: the session closes right here.
                    return [fc.name for fc in call.function_calls]
                content = getattr(message, "server_content", None)
                if content is not None and getattr(content, "turn_complete", False):
                    return []
            return []
        return await asyncio.wait_for(read(), timeout)


async def run_live(cases: list[Case], modes: Iterable[str], *, repeat: int = 1,
                   timeout: float = 25.0, client=None, model: str = "") -> dict:
    import jarvis.main as app
    if client is None:
        from google import genai
        client = genai.Client(api_key=app._get_api_key(), http_options={"api_version": "v1beta"})
    model = model or app.LIVE_MODEL
    registries = _registries()
    out: dict = {"model": model, "repeat": repeat, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "modes": {}}
    for mode in modes:
        setup = build_setup(mode, registries=registries)
        rows, counts = [], {"engine": 0, "accepted": 0, "other": 0, "no_tool": 0, "error": 0}
        for case in cases:
            for attempt in range(repeat):
                try:
                    called = await _first_tools(client, model, setup, case.text, timeout)
                    outcome = score(case, called)
                except Exception as exc:          # one failed connect must not end the run
                    called, outcome = [], "error"
                    print(f"  {mode} {case.id}: {type(exc).__name__}", file=sys.stderr)
                counts[outcome] += 1
                rows.append({"case": case.id, "attempt": attempt, "called": called, "outcome": outcome})
        applicable = [r for r in rows if next(c for c in cases if c.id == r["case"]).engine]
        out["modes"][mode] = {
            "tools": len(setup.declarations), "hidden": sorted(setup.hidden), "counts": counts,
            "engine_rate": round(sum(r["outcome"] == "engine" for r in applicable) / max(1, len(applicable)), 3),
            "useful_rate": round((counts["engine"] + counts["accepted"]) / max(1, len(rows)), 3),
            "rows": rows,
        }
    return out


def _print_offline(report: dict) -> None:
    print(f"Offline tool-choice check (readiness: {report['ready']})")
    for mode, row in report["modes"].items():
        print(f"  {mode:14s} tools={row['tools']:3d} decl={row['declaration_bytes']:6d} B "
              f"prompt={row['system_prompt_chars']:6d} ch routing={'yes' if row['routing_section'] else 'no ':3s} "
              f"hidden={','.join(row['hidden']) or '-'}")
        if row["cases_without_an_offered_tool"]:
            print("     NO TOOL OFFERED FOR: " + ", ".join(row["cases_without_an_offered_tool"]))


def _print_live(result: dict) -> None:
    print(f"Live tool choice — {result['model']} (repeat {result['repeat']})")
    for mode, row in result["modes"].items():
        c = row["counts"]
        print(f"  {mode:14s} engine_rate={row['engine_rate']:.2f} useful={row['useful_rate']:.2f} "
              f"engine={c['engine']} accepted={c['accepted']} other={c['other']} "
              f"no_tool={c['no_tool']} error={c['error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jarvis.eval.tool_choice")
    parser.add_argument("--live", action="store_true", help="ask the real Gemini Live model (needs the key)")
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--actual-readiness", action="store_true",
                        help="offline: use this computer's readiness instead of assuming Windows")
    args = parser.parse_args(argv)
    cases = load_cases()
    if not args.live:
        report = offline_report(cases, args.modes, ready=None if args.actual_readiness else ASSUMED_READY)
        _print_offline(report)
        return 1 if any(r["cases_without_an_offered_tool"] for r in report["modes"].values()) else 0
    result = asyncio.run(run_live(cases, args.modes, repeat=max(1, args.repeat), timeout=args.timeout))
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(result, indent=1), encoding="utf-8")
    _print_live(result)
    print(f"Saved {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
