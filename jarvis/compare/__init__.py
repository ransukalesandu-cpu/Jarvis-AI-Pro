"""Ask several AI providers the same question in parallel and compare (Cherry Studio parity P3).

Results (answer, model, latency, rough cost) are kept in memory for the web UI and
the owner can pick a winner; winners are counted per task so the owner can make that
provider the preferred route for the task (an explicit, owner-approved setting).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from jarvis.core import text_brain

MAX_PROVIDERS = 5
TIMEOUT_S = 90.0
# USD per 1M tokens (input, output) for a rough, clearly-labelled estimate only.
_PRICE = {"gemini": (0.30, 2.50), "openai": (1.25, 10.0), "claude": (3.0, 15.0), "groq": (0.59, 0.79), "ollama": (0.0, 0.0)}

Asker = Callable[[str, str, str], dict]


@dataclass
class Answer:
    provider: str
    ok: bool
    text: str = ""
    model: str = ""
    latency_ms: float = 0.0
    est_cost_usd: float = 0.0
    error: str = ""


@dataclass
class Comparison:
    id: str
    prompt: str
    task: str
    created: float
    answers: list[Answer] = field(default_factory=list)
    winner: str = ""


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _cost(provider: str, prompt: str, answer: str) -> float:
    pin, pout = _PRICE.get(provider, (0.0, 0.0))
    return round((_tokens(prompt) * pin + _tokens(answer) * pout) / 1_000_000, 6)


def _default_ask(provider: str, prompt: str, system: str) -> dict:
    return text_brain.ask_provider(provider, prompt, system)


_history: list[Comparison] = []
_hist_lock = threading.Lock()


def compare(prompt: str, providers: Optional[list[str]] = None, *, task: str = "chat",
            system: str = "You are a helpful, accurate assistant. Answer concisely.",
            ask: Optional[Asker] = None, timeout: float = TIMEOUT_S) -> Comparison:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("what should I ask the models?")
    wanted = [text_brain.normalize(p) for p in (providers or []) if str(p).strip()]
    if not wanted:
        wanted = text_brain.configured()
    wanted = [p for p in dict.fromkeys(wanted) if p in text_brain.PROVIDERS][:MAX_PROVIDERS]
    if not wanted:
        raise ValueError("no known providers to compare")
    ask = ask or _default_ask
    result = Comparison(uuid.uuid4().hex[:10], prompt, task, time.time())

    def one(provider: str) -> Answer:
        started = time.monotonic()
        try:
            r = ask(provider, prompt, system)
            text = str(r.get("text") or "").strip()
            if not text:
                raise RuntimeError("empty answer")
            ms = float(r.get("latency_ms") or (time.monotonic() - started) * 1000)
            return Answer(provider, True, text, str(r.get("model") or ""), round(ms, 1), _cost(provider, prompt, text))
        except Exception as e:
            return Answer(provider, False, error=f"{type(e).__name__}: {e}"[:200],
                          latency_ms=round((time.monotonic() - started) * 1000, 1))

    pool = ThreadPoolExecutor(max_workers=len(wanted), thread_name_prefix="compare")
    futures = {pool.submit(one, p): p for p in wanted}
    got: dict[str, Answer] = {}
    try:
        for fut in as_completed(futures, timeout=timeout):
            got[futures[fut]] = fut.result()
    except TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)     # never wait for a hung provider
    for p in wanted:
        result.answers.append(got.get(p) or Answer(p, False, error="timed out"))
    with _hist_lock:
        _history.append(result)
        del _history[:-20]
    return result


def latest() -> Optional[Comparison]:
    with _hist_lock:
        return _history[-1] if _history else None


def get(cid: str) -> Optional[Comparison]:
    with _hist_lock:
        return next((c for c in _history if c.id == cid), None)


def _wins_path() -> Path:
    from jarvis.core.user_data import user_data_dir
    return user_data_dir() / "compare_wins.json"


def pick_winner(provider: str, cid: str = "") -> dict:
    """Record the owner's choice; returns win counts per task for that provider."""
    c = get(cid) if cid else latest()
    if c is None:
        raise ValueError("there is no comparison to pick from")
    provider = text_brain.normalize(provider)
    if provider not in {a.provider for a in c.answers if a.ok}:
        raise ValueError(f"{provider} did not answer in that comparison")
    c.winner = provider
    path = _wins_path()
    try:
        wins = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        wins = {}
    task_wins = wins.setdefault(c.task, {})
    task_wins[provider] = int(task_wins.get(provider, 0)) + 1
    path.write_text(json.dumps(wins, indent=2), encoding="utf-8")
    return task_wins


def wins() -> dict:
    try:
        return json.loads(_wins_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def to_dict(c: Comparison) -> dict:
    return asdict(c)


def summary(c: Comparison, *, chars: int = 600) -> str:
    lines = [f"Compared {len(c.answers)} models on: {c.prompt[:120]}"]
    for a in c.answers:
        if a.ok:
            lines.append(f"\n## {a.provider}{' (' + a.model + ')' if a.model else ''} — {a.latency_ms / 1000:.1f}s"
                         f"{', ~$' + format(a.est_cost_usd, '.4f') if a.est_cost_usd else ''}\n{a.text[:chars]}"
                         f"{'…' if len(a.text) > chars else ''}")
        else:
            lines.append(f"\n## {a.provider} — failed: {a.error}")
    return "\n".join(lines)
