"""Read-only snapshots of the Cherry-parity features for the web UI's Features Hub window.

The page never calls a feature directly: it asks for a snapshot (``feature.refresh``) and
every action button submits an ordinary typed command through the CommandGate, so the
normal security tiers, confirmations and audit apply. Snapshots are bounded, redacted
(secrets and home paths scrubbed) and only built while commands are available (not
locked, waiting for a PIN, silent or in Guest Mode). No Qt in this module.
"""
from __future__ import annotations

import time
from typing import Callable

FEATURES = ("knowledge", "notes", "telegram", "providers", "compare", "backup", "profiles", "files", "apps")
MAX_ITEMS = 30
MAX_TITLE = 120
MAX_DETAIL = 200
MAX_SUMMARY = 200


def _clip(text, n: int) -> str:
    from . import redact
    t = redact.scrub(" ".join(str(text or "").split()))
    return t if len(t) <= n else t[: n - 1] + "…"


def _item(title, detail="") -> dict:
    return {"title": _clip(title, MAX_TITLE) or "—", "detail": _clip(detail, MAX_DETAIL)}


def _knowledge():
    from jarvis.knowledge import get_store
    store = get_store()
    active = store.get_active()
    s = store.stats()
    items = [_item(f"{b['name']}{' (active)' if b['name'] == active else ''}",
                   f"{b['sources']} sources · {b['chunks']} chunks{' · ' + b['description'] if b['description'] else ''}")
             for b in store.list_bases()]
    return f"{s['bases']} knowledge bases · {s['sources']} sources · {s['vectors']} embedded", items


def _notes():
    from jarvis import notes
    all_notes = notes.all_notes()
    items = [_item(n.title, (", ".join(n.tags) + " · " if n.tags else "") + time.strftime("%Y-%m-%d %H:%M", time.localtime(n.updated)))
             for n in all_notes[:MAX_ITEMS]]
    return f"{len(all_notes)} notes", items


def _telegram():
    from jarvis.channels import service
    ch = service.get_channel()
    if ch is None:
        return ("Not set up — add telegram_bot_token to config/api_keys.json and restart"
                if not service.configured_token() else "Token set, channel not running (restart JARVIS)"), []
    paired = ch.paired()
    items = [_item(v.get("name") or "chat", f"paired {time.strftime('%Y-%m-%d', time.localtime(v.get('paired_at', 0)))}")
             for v in paired.values()]
    state = "running" if ch.running else "stopped"
    return f"Channel {state} · {len(paired)} paired chat(s){' · ' + ch.last_error if ch.last_error else ''}", items


def _providers():
    from jarvis.core import text_brain, usage_meter
    configured = set(text_brain.configured())
    today = usage_meter.day_usage()
    items = []
    for p in text_brain.PROVIDERS:
        state = "local" if p == "ollama" else ("key set" if p in configured else "no key")
        row = today.get(p, {})
        items.append(_item(p, f"{state} · {row.get('calls', 0)} calls today · ~${row.get('cost_usd', 0.0):.3f}"))
    total = sum(r.get("cost_usd", 0.0) for r in today.values())
    budget = float(usage_meter.settings().get("daily_budget_usd") or 0)
    return f"Today ~${total:.3f}" + (f" of ${budget:.2f} budget" if budget else ""), items


def _compare():
    from jarvis import compare
    c = compare.latest()
    if c is None:
        return "No comparison yet", []
    items = [_item(f"{a.provider}{' ★' if a.provider == c.winner else ''}",
                   (f"{a.latency_ms / 1000:.1f}s · " + a.text) if a.ok else f"failed: {a.error}") for a in c.answers]
    return f"Last: {c.prompt}", items


def _backup():
    from jarvis import backup
    cfg = backup.load_config()
    items = [_item(b.name, f"{b.stat().st_size // 1024} KB") for b in backup.list_backups()[:MAX_ITEMS]]
    sched = f"every {cfg['every_days']:g} day(s)" if cfg.get("every_days") else "off"
    return f"{len(items)} backup(s) · schedule {sched} · password {'set' if backup._password() else 'not set'}", items


def _profiles():
    from jarvis import assistants
    cur = assistants.active_name()
    items = [_item(f"{n}{' (active)' if n == cur else ''}", v["instructions"]) for n, v in assistants.all_profiles().items()]
    return f"Active: {cur or 'default JARVIS'}", items


def _files():
    from jarvis import library
    rows = library.items(limit=MAX_ITEMS)
    return f"{len(rows)} recent file(s)", [_item(r["name"], f"{r['kind']} · {r['path']}") for r in rows]


def _apps():
    from jarvis import library
    apps = library.mini_apps()
    return f"{len(apps)} mini app(s)", [_item(k, v) for k, v in sorted(apps.items())]


_BUILDERS: dict[str, Callable[[], tuple[str, list[dict]]]] = {
    "knowledge": _knowledge, "notes": _notes, "telegram": _telegram, "providers": _providers, "compare": _compare,
    "backup": _backup, "profiles": _profiles, "files": _files, "apps": _apps,
}


def snapshot(feature: str) -> tuple[str, list[dict]]:
    """(summary, items) for a feature; never raises."""
    if feature not in _BUILDERS:
        return "Unknown feature", []
    try:
        summary, items = _BUILDERS[feature]()
        clean = [_item(i.get("title"), i.get("detail")) for i in items[:MAX_ITEMS]]   # re-clip and scrub every field
        return _clip(summary, MAX_SUMMARY) or "—", clean
    except Exception as e:
        return _clip(f"Unavailable ({type(e).__name__})", MAX_SUMMARY), []


UNAVAILABLE = {
    "locked": "JARVIS is locked", "auth_required": "Waiting for the owner PIN", "silent": "Silent mode",
    "guest": "Hidden in Guest Mode", "unavailable": "Not available right now",
}
