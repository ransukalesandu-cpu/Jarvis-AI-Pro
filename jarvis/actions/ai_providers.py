"""Voice tool: AI provider manager — keys status, connection test, task routes, usage and budget."""
from __future__ import annotations

import time

from jarvis.core import text_brain, usage_meter

_ACTIONS = ("status", "test", "set_route", "routes", "usage", "set_budget")


def _routes() -> dict:
    from jarvis.core import provider_settings, task_router
    return task_router.routing_from_config(provider_settings._read()) or {}


def ai_providers(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "status":
            configured = set(text_brain.configured())
            perf = {}
            try:
                perf = text_brain.get_router().provider_performance()
            except Exception:
                perf = {}
            today = usage_meter.day_usage()
            lines = ["AI providers:"]
            for prov in text_brain.PROVIDERS:
                state = "local" if prov == "ollama" else ("key set" if prov in configured else "no key")
                lat = perf.get(prov, {}).get("latency_ewma_ms") if isinstance(perf.get(prov), dict) else None
                used = today.get(prov, {}).get("calls", 0)
                lines.append(f"- {prov}: {state}{f', ~{lat:.0f} ms' if lat else ''}{f', {used} calls today' if used else ''}")
            return "\n".join(lines)
        if action == "test":
            prov = text_brain.normalize(str(p.get("provider") or ""))
            started = time.monotonic()
            r = text_brain.ask_provider(prov, "Reply with the single word OK.", "You are a connection test.")
            ms = (time.monotonic() - started) * 1000
            return f"{prov} works ({r.get('model') or 'default model'}, {ms:.0f} ms): {str(r.get('text'))[:40]}"
        if action in ("set_route", "routes"):
            from jarvis.core import provider_settings, task_router
            if action == "set_route":
                task = str(p.get("task") or "").strip().lower()
                prov = text_brain.normalize(str(p.get("provider") or ""))
                if task not in task_router.CATEGORIES:
                    return f"Unknown task '{task}'. Tasks: {', '.join(task_router.CATEGORIES)}."
                if prov not in task_router.PROVIDERS:
                    return f"Unknown provider '{prov}'."
                cfg = provider_settings._read()
                table = dict(cfg.get("task_routing") or {})
                table[task] = prov
                cfg["task_routing"] = table
                provider_settings._write(cfg)
            routes = _routes()
            if not routes:
                return "No task routes set; every task uses the preferred provider."
            return "Task routes:\n" + "\n".join(f"- {k}: {v}" for k, v in routes.items())
        if action == "usage":
            period = str(p.get("period") or "today").lower()
            if period.startswith("month"):
                return usage_meter.report(usage_meter.month_usage(), "this month")
            return usage_meter.report(usage_meter.day_usage(), "today")
        budget = float(p.get("budget_usd") or 0)
        usage_meter.save_settings(daily_budget_usd=max(0.0, budget))
        return f"Daily AI budget alert set to ${budget:.2f}." if budget > 0 else "Daily budget alert turned off."
    except ValueError as e:
        return f"AI providers: {e}"
    except RuntimeError as e:
        return f"AI providers: test failed ({e})."


TOOL = {
    "name": "ai_providers",
    "description": (
        "Manage JARVIS's AI providers (gemini, claude, openai, groq, local ollama): status (which keys are set, "
        "speed, calls today), test a provider's connection, set_route (which provider handles a task such as "
        "coding, writing, reasoning, simple), routes, usage (today or month, estimated cost), set_budget (daily "
        "cost alert in USD; 0 = off). API keys themselves are never read out or changed by voice."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "provider": {"type": "STRING"},
            "task": {"type": "STRING", "description": "Task category for set_route."},
            "period": {"type": "STRING", "description": "today or month (usage)."},
            "budget_usd": {"type": "NUMBER", "description": "Daily budget in USD (set_budget)."},
        },
        "required": ["action"],
    },
    "handler": ai_providers,
    "risk": "write",
    "timeout": 60,
}
