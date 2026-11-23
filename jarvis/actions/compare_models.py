"""Voice tool: ask Claude, Gemini, GPT (and others) the same question and compare their answers."""
from __future__ import annotations

from jarvis import compare as cmp

_ACTIONS = ("compare", "show", "pick_winner", "wins")


def compare_models(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "compare").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown compare action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "compare":
            providers = p.get("providers") or []
            if isinstance(providers, str):
                providers = [x.strip() for x in providers.split(",")]
            if speak:
                speak("Asking the models now.")
            c = cmp.compare(str(p.get("prompt") or ""), providers, task=str(p.get("task") or "chat"))
            return (cmp.summary(c) + "\n\nGive the owner a short verdict comparing these answers (accuracy, "
                    "depth, speed). They can say which one won.")
        if action == "show":
            c = cmp.latest()
            return cmp.summary(c, chars=3000) if c else "No comparison yet."
        if action == "pick_winner":
            counts = cmp.pick_winner(str(p.get("provider") or ""))
            return "Noted. Wins for this task so far: " + ", ".join(f"{k}: {v}" for k, v in counts.items())
        w = cmp.wins()
        if not w:
            return "No winners recorded yet."
        return "Winners by task:\n" + "\n".join(
            f"- {task}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1]))
            for task, c in w.items())
    except ValueError as e:
        return f"Compare: {e}"


TOOL = {
    "name": "compare_models",
    "description": (
        "Ask several AI models (gemini, claude, openai/GPT, groq, ollama) the same prompt in parallel and compare "
        "answers, speed and rough cost. Use when the owner says 'ask Claude, Gemini and GPT…' or 'which AI is better "
        "for…'. 'show' repeats the last comparison in full, 'pick_winner' records the owner's choice, 'wins' lists "
        "winners per task."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "prompt": {"type": "STRING", "description": "The question to send to every model."},
            "providers": {"type": "STRING", "description": "Comma-separated, e.g. 'claude,gemini,openai'. Empty = all configured."},
            "task": {"type": "STRING", "description": "Task label for winner stats, e.g. coding, writing, chat."},
            "provider": {"type": "STRING", "description": "Winner (pick_winner)."},
        },
        "required": ["action"],
    },
    "handler": compare_models,
    "risk": "read",
    "timeout": 150,
}
