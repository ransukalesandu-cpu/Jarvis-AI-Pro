"""Voice access to skills (core/skills.py): list, load, create, delete, enable, disable."""
from __future__ import annotations

from jarvis.core.skills import SkillError, get_skill_registry


def skills(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    action = str(p.get("action") or "list").strip().lower()
    name = str(p.get("name") or "").strip().lower()
    registry = get_skill_registry()
    if action == "list":
        rows = registry.scan()
        if not rows:
            text = "No skills installed."
        else:
            text = "\n".join(
                f"{s.name}{'' if s.enabled else ' (disabled)'} [{s.source}]: {s.description}" for s in rows)
        if registry.errors:
            text += "\nSkipped: " + "; ".join(f"{k}: {v}" for k, v in registry.errors.items())
        return text
    if action == "use":
        skill = registry.get(name)
        if skill is None:
            return f"No skill named '{name}'."
        if not skill.enabled:
            return f"Skill '{name}' is disabled."
        return f"Skill '{skill.name}' (v{skill.version}). Follow these steps:\n\n{skill.body}"
    if action == "create":
        try:
            skill = registry.create(name, p.get("description", ""), p.get("body", ""),
                                    overwrite=bool(p.get("overwrite", False)))
        except SkillError as exc:
            return f"Skill not saved: {exc}"
        return f"Skill '{skill.name}' saved."
    if action == "delete":
        return f"Skill '{name}' deleted." if registry.delete(name) else f"No user skill named '{name}'."
    if action in ("enable", "disable"):
        ok = registry.set_enabled(name, action == "enable")
        return f"Skill '{name}' {action}d." if ok else f"No skill named '{name}'."
    return f"Unknown action '{action}'. Use list, use, create, delete, enable or disable."


TOOL = {
    "name": "skills",
    "description": (
        "Skills are saved step-by-step instructions for a kind of task. list shows them; "
        "use loads one by name so you can follow it; create saves a new one (name, "
        "description, body in Markdown); delete, enable and disable manage them. "
        "A skill is only instructions — carry out its steps with your normal tools."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | use | create | delete | enable | disable"},
            "name": {"type": "STRING", "description": "Skill name, e.g. weekly-report"},
            "description": {"type": "STRING", "description": "For create: one line saying when to use it"},
            "body": {"type": "STRING", "description": "For create: the instructions in Markdown"},
            "overwrite": {"type": "BOOLEAN", "description": "For create: replace an existing skill"},
        },
        "required": ["action"],
    },
    "handler": skills,
    "risk": "write",
}
