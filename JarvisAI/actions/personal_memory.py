"""Owner-only controls for viewing or deleting the opt-in cloud personal profile."""
from __future__ import annotations

import json
from typing import Any

from core.personal_cloud_memory import (
    clear_personal_memories,
    forget_personal_memory,
    list_personal_memories,
)


def personal_memory(parameters: dict, **_kwargs) -> str:
    """List saved personal facts or request guarded deletion of selected/all facts."""
    operation = str(parameters.get("operation") or "list").strip().lower()
    try:
        if operation == "list":
            from memory.config_manager import get_personal_cloud_memory_enabled
            if not get_personal_cloud_memory_enabled():
                return (
                    "Personal cloud memory is disabled on this device. I did not load the saved profile. "
                    "Enable personal_cloud_memory to view it, or use operation=clear to delete it without viewing."
                )
            rows = list_personal_memories()
            visible = [
                {"fact_key": row["fact_key"], "value": row["value"]}
                for row in rows
                if row.get("fact_key") and row.get("value")
            ]
            if not visible:
                return "No personal profile facts are stored in the Supabase memory."
            return (
                "Saved user-stated personal profile facts (you can correct them by stating "
                "the updated fact, or delete a category):\n"
                + json.dumps(visible, ensure_ascii=False)
            )
        if operation == "forget":
            fact_key = str(parameters.get("fact_key") or "").strip().lower()
            if not fact_key:
                return "Tell me which personal fact category to forget. Nothing was deleted."
            forget_personal_memory(fact_key)
            return f"Requested deletion of the saved '{fact_key}' personal fact."
        if operation == "clear":
            clear_personal_memories()
            return "The Supabase personal profile has been cleared."
        return "Choose operation list, forget, or clear."
    except Exception as exc:
        return (
            "The cloud personal-memory operation failed safely "
            f"({type(exc).__name__}). No successful change was confirmed."
        )


TOOL = {
    "name": "personal_memory",
    "description": (
        "Manage only the user's opted-in Supabase personal profile. Use operation=list to tell "
        "the user what saved personal facts are available; only show a fact when relevant or asked. "
        "Use operation=forget with one exact fact_key to delete that category, or operation=clear "
        "to delete the whole cloud personal profile. Forget and clear require explicit confirmation "
        "through JARVIS's protected action gate. Never use this tool to store guesses, save raw chats, "
        "or store secrets. Automatic capture separately accepts only directly stated facts."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {
                "type": "STRING",
                "enum": ["list", "forget", "clear"],
                "description": "List existing personal facts, delete one category, or clear all profile facts.",
            },
            "fact_key": {
                "type": "STRING",
                "enum": [
                    "name", "siblings", "family_context", "education", "occupation",
                    "interests", "preferences", "goals", "language", "communication_style",
                ],
                "description": "Required only for operation=forget.",
            },
        },
        "required": ["operation"],
    },
    "handler": personal_memory,
}
