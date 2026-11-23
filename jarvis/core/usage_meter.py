"""Per-provider usage and rough cost across ALL text providers, with a daily budget alert.

Records only provider, model, character counts and latency — never prompts, answers
or keys. Token counts are estimated (chars / 4) and prices are list-price estimates,
so this is visibility, not billing. Stored per month in ``<data>/usage/YYYY-MM.json``.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# USD per 1M tokens (input, output); rough defaults, the owner can override via set_prices().
PRICES: dict[str, tuple[float, float]] = {
    "gemini": (0.30, 2.50), "openai": (1.25, 10.0), "claude": (3.0, 15.0), "groq": (0.59, 0.79), "ollama": (0.0, 0.0),
}
_lock = threading.Lock()
_notifier: Optional[Callable[[str], None]] = None


def _dir() -> Path:
    from jarvis.core.user_data import user_data_dir
    d = user_data_dir() / "usage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _month_file(ts: float) -> Path:
    return _dir() / (time.strftime("%Y-%m", time.localtime(ts)) + ".json")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def settings() -> dict:
    return _load(_dir() / "settings.json")


def save_settings(**changes) -> dict:
    s = settings()
    s.update({k: v for k, v in changes.items() if v is not None})
    (_dir() / "settings.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def set_notifier(fn: Optional[Callable[[str], None]]) -> None:
    global _notifier
    _notifier = fn


def estimate_cost(provider: str, in_tokens: int, out_tokens: int) -> float:
    custom = settings().get("prices", {}).get(provider)
    pin, pout = (custom if isinstance(custom, (list, tuple)) and len(custom) == 2 else PRICES.get(provider, (0.0, 0.0)))
    return (in_tokens * float(pin) + out_tokens * float(pout)) / 1_000_000


def record(provider: str, model: str = "", *, in_chars: int = 0, out_chars: int = 0, latency_ms: float = 0.0,
           now: Optional[float] = None) -> None:
    """Fail-soft: never raises into the caller."""
    try:
        ts = now if now is not None else time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        tin, tout = max(0, in_chars) // 4, max(0, out_chars) // 4
        cost = estimate_cost(provider, tin, tout)
        alert = ""
        with _lock:
            path = _month_file(ts)
            data = _load(path)
            d = data.setdefault(day, {})
            row = d.setdefault(provider, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0,
                                          "latency_ms_total": 0.0, "models": {}})
            row["calls"] += 1
            row["in_tokens"] += tin
            row["out_tokens"] += tout
            row["cost_usd"] = round(row["cost_usd"] + cost, 6)
            row["latency_ms_total"] = round(row["latency_ms_total"] + float(latency_ms or 0), 1)
            if model:
                row["models"][model[:60]] = row["models"].get(model[:60], 0) + 1
            path.write_text(json.dumps(data, indent=1), encoding="utf-8")
            budget = float(settings().get("daily_budget_usd") or 0)
            total = sum(r.get("cost_usd", 0.0) for r in d.values())
            meta = data.setdefault("_alerts", {})
            if budget > 0 and total >= budget and not meta.get(day):
                meta[day] = True
                path.write_text(json.dumps(data, indent=1), encoding="utf-8")
                alert = (f"AI usage today is about ${total:.2f}, over your ${budget:.2f} daily budget. "
                         "Check the provider consoles for exact billing.")
        if alert and _notifier:
            _notifier(alert)
    except Exception:
        return


def day_usage(day: Optional[str] = None) -> dict:
    ts = time.time()
    day = day or time.strftime("%Y-%m-%d", time.localtime(ts))
    data = _load(_dir() / (day[:7] + ".json"))
    return data.get(day, {})


def month_usage(month: Optional[str] = None) -> dict:
    month = month or time.strftime("%Y-%m")
    data = _load(_dir() / f"{month}.json")
    totals: dict[str, dict] = {}
    for day, providers in data.items():
        if day.startswith("_"):
            continue
        for p, row in providers.items():
            t = totals.setdefault(p, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "cost_usd": 0.0})
            for k in t:
                t[k] = round(t[k] + row.get(k, 0), 6) if k == "cost_usd" else t[k] + row.get(k, 0)
    return totals


def report(rows: dict, label: str) -> str:
    if not rows:
        return f"No AI usage recorded {label}."
    total = sum(r.get("cost_usd", 0.0) for r in rows.values())
    lines = [f"AI usage {label} (estimates): about ${total:.3f}"]
    for p, r in sorted(rows.items(), key=lambda kv: -kv[1].get("cost_usd", 0)):
        lines.append(f"- {p}: {r['calls']} calls, ~{r['in_tokens'] + r['out_tokens']:,} tokens, ~${r['cost_usd']:.3f}")
    return "\n".join(lines)
