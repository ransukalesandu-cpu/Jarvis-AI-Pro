"""Voice tool: switch between assistant profiles (coding, writer, designer, tutor, custom ones)."""
from __future__ import annotations

from jarvis import assistants as ap

_ACTIONS = ("list", "switch", "current", "create", "delete")


def assistant_profiles(parameters: dict, speak=None, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    if action not in _ACTIONS:
        return f"Unknown action '{action}'. Use one of: {', '.join(_ACTIONS)}."
    try:
        if action == "list":
            cur = ap.active_name()
            rows = [f"- {n}{' (active)' if n == cur else ''}{' [built-in]' if v.get('builtin') else ''}: "
                    f"{v['instructions'][:80]}" for n, v in ap.all_profiles().items()]
            return "Assistant profiles:\n" + "\n".join(rows) + ("" if cur else "\nCurrently: default JARVIS.")
        if action == "current":
            prof = ap.active()
            return f"Active profile: {prof['name']}." if prof else "No profile active: default JARVIS."
        if action == "switch":
            prof = ap.activate(str(p.get("name") or ""))
            if not prof:
                return "Back to default JARVIS."
            extra = f" Knowledge base: {prof['knowledge_base']}." if prof.get("knowledge_base") else ""
            return (f"Switched to the {prof['name']} profile.{extra} From now on follow these instructions "
                    f"(identity and security unchanged): {prof['instructions']}")
        if action == "create":
            tools = p.get("allowed_tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(",") if t.strip()]
            name = ap.save_profile(str(p.get("name") or ""), str(p.get("instructions") or ""),
                                   provider=str(p.get("provider") or ""),
                                   knowledge_base=str(p.get("knowledge_base") or ""), allowed_tools=tools)
            return f"Profile '{name}' saved. Say 'switch to {name}' to use it."
        ap.delete_profile(str(p.get("name") or ""))
        return "Profile deleted."
    except (ValueError, KeyError) as e:
        return f"Profiles: {e.args[0] if e.args else e}"


TOOL = {
    "name": "assistant_profiles",
    "description": (
        "Assistant profiles = focused roles with their own instructions, optional preferred AI provider, knowledge "
        "base and tool allow-list (built-in: coding, writer, designer, tutor). 'switch' (name; 'default' returns to "
        "plain JARVIS), 'list', 'current', 'create', 'delete'. Identity, voice and security never change."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(_ACTIONS)},
            "name": {"type": "STRING"},
            "instructions": {"type": "STRING", "description": "Role instructions (create)."},
            "provider": {"type": "STRING", "description": "Preferred text provider (create), optional."},
            "knowledge_base": {"type": "STRING", "description": "Knowledge base to activate (create), optional."},
            "allowed_tools": {"type": "STRING", "description": "Comma-separated tool allow-list (create), optional."},
        },
        "required": ["action"],
    },
    "handler": assistant_profiles,
    "risk": "write",
    "timeout": 30,
}
