"""Read-only tools for the text fallback while Gemini Live is down.

When Live is not connected and an Anthropic key is configured, the text
fallback can let Claude call a few SAFE, read-only actions instead of only
apologising: system status, battery, weather, web search and (when the owner
allows provider memory access) recall_memory. Nothing that writes, deletes,
opens, sends or controls anything is reachable from here.

Every call goes through the same gate as a Live tool call: security.guard()
(which applies ActionDispatcher's tier policy, Privacy Lock and the provenance
checks) and is written to the action log. The honesty rule still holds: the
model is told that only a tool that actually ran and returned counts as done.
"""
from __future__ import annotations

from typing import Any, Callable

from jarvis.core.provider_settings import claude_model, get_provider_api_key

# The ONLY tools the fallback may call. Read-only by construction.
SAFE_FALLBACK_TOOLS = ("system_status", "battery_status", "weather_report", "web_search",
                       "recall_memory")

_INLINE = {
    "system_status": {
        "description": "Current CPU, memory, disk and network status of this computer.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "recall_memory": {
        "description": "Search the owner's saved memories for facts relevant to a query.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look up."}},
            "required": ["query"]},
    },
}

TOOL_RULES = (
    "\n\nHYBRID TEXT FALLBACK RULES: Gemini Live is offline. You can call ONLY the "
    "read-only tools provided here (status, battery, weather, web search, memory "
    "recall). You cannot open apps, change files or settings, send messages, or "
    "control the computer. Never say you did something unless a tool call in this "
    "conversation actually ran and returned that result; if a request needs an "
    "action you have no tool for, say so plainly and suggest trying again when "
    "voice is back. Keep answers short and speakable."
)


def gemini_to_json_schema(schema: Any) -> dict:
    """Gemini function-declaration schema (OBJECT/STRING...) -> JSON Schema."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type":
            out["type"] = str(value).lower()
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {k: gemini_to_json_schema(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = gemini_to_json_schema(value)
        elif key in ("required", "enum", "description"):
            out[key] = value
    if out.get("type") == "object":
        out.setdefault("properties", {})
    return out


class FallbackToolbox:
    """The allow-listed tools, their declarations for Claude, and a gated runner.

    ``registry`` is the live ActionRegistry (has / declarations / run);
    ``recall`` answers recall_memory; ``memory_enabled`` gates it.
    ``guard`` and ``log`` default to core.security.guard and
    core.action_log.record, injectable for tests.
    """

    def __init__(self, registry: Any = None, *, recall: Callable[[str], str] | None = None,
                 system_status: Callable[[], str] | None = None, memory_enabled: bool = False,
                 guard: Callable | None = None, log: Callable | None = None):
        self.registry = registry
        self.recall = recall
        self.system_status = system_status
        self.memory_enabled = bool(memory_enabled)
        if guard is None:
            from jarvis.core import security
            guard = security.guard
        if log is None:
            from jarvis.core import action_log
            log = action_log.record
        self._guard, self._log = guard, log
        self.ran: list[str] = []

    def _registry_decl(self, name: str) -> dict | None:
        reg = self.registry
        if reg is None or not getattr(reg, "has", lambda _n: False)(name):
            return None
        for decl in reg.get_tool_declarations():
            if decl.get("name") == name:
                return decl
        return None

    def available(self) -> list[str]:
        names = []
        for name in SAFE_FALLBACK_TOOLS:
            if name == "recall_memory":
                if self.memory_enabled and self.recall is not None:
                    names.append(name)
            elif name == "system_status":
                if self.system_status is not None:
                    names.append(name)
            elif self._registry_decl(name) is not None:
                names.append(name)
        return names

    def tools(self) -> list[dict]:
        """Anthropic tool definitions for the available allow-listed tools."""
        out = []
        for name in self.available():
            if name in _INLINE:
                out.append({"name": name, **_INLINE[name]})
                continue
            decl = self._registry_decl(name) or {}
            params = dict(decl.get("parameters") or {})
            # The registry adds an optional "device" argument to every tool;
            # the fallback always runs on this machine.
            if isinstance(params.get("properties"), dict):
                params["properties"] = {k: v for k, v in params["properties"].items() if k != "device"}
            out.append({"name": name,
                        "description": str(decl.get("description") or name)[:1024],
                        "input_schema": gemini_to_json_schema(params)})
        return out

    def run(self, name: str, args: dict | None) -> str:
        """Run one allow-listed tool through security.guard and the action log."""
        from jarvis.core import action_log
        from jarvis.core.tool_runtime import result_status
        args = dict(args or {})
        args.pop("device", None)
        timer = action_log.Timer()
        if name not in self.available():
            result = f"The tool '{name}' is not available while voice is offline."
            self._log(name, args, result, status="error", risk="read", duration_ms=timer.ms)
            return result
        if name == "recall_memory":
            work = lambda: self.recall(str(args.get("query") or ""))      # noqa: E731
        elif name == "system_status":
            work = lambda: self.system_status()                          # noqa: E731
        else:
            work = lambda: self.registry.run(name, args, {})              # noqa: E731
        try:
            result = str(self._guard(name, args, work))
        except Exception as exc:
            result = f"The {name.replace('_', ' ')} tool failed ({type(exc).__name__})."
        self._log(name, args, result, status=result_status(result), risk="read",
                  duration_ms=timer.ms)
        self.ran.append(name)
        return result


def _text(response: Any) -> str:
    return "".join(getattr(b, "text", "") for b in getattr(response, "content", []) or []
                   if getattr(b, "type", "") == "text").strip()


def answer_with_tools(prompt: str, system_prompt: str, toolbox: FallbackToolbox, *,
                      model: str | None = None, client_factory: Callable | None = None,
                      max_steps: int = 4, timeout: float = 45.0,
                      task_text: str | None = None, api_key: str | None = None) -> dict:
    """Answer with Claude, letting it call the allow-listed tools.

    Returns {"text", "model", "provider": "claude", "tools_ran": [...]}.
    Raises when Claude cannot be reached or does not finish within
    ``max_steps``, so the caller can fall back to the plain text route. ``api_key`` is the key the caller selected from its
    config; without it the shared provider settings are used.
    """
    from jarvis.core.claude_usage import record_call
    from jarvis.core.task_router import classify

    key = (api_key or "").strip() or get_provider_api_key("anthropic")
    if not key:
        raise RuntimeError("No Anthropic key configured.")
    if model is None:
        # ``task_text`` is the owner's request; ``prompt`` may wrap it.
        heavy = classify(task_text or prompt) in ("coding", "planning", "reasoning", "writing")
        model = claude_model("strong" if heavy else "fast")
    if client_factory is None:
        import anthropic

        def client_factory(t):
            return anthropic.Anthropic(api_key=key, timeout=t, max_retries=1)
    client = client_factory(timeout)
    tools = toolbox.tools()
    system = (system_prompt or "") + TOOL_RULES
    messages: list[dict] = [{"role": "user", "content": prompt}]
    for _step in range(max(1, int(max_steps))):
        request = {"model": model, "max_tokens": 4096, "system": system, "messages": messages}
        if tools:
            request["tools"] = tools
        response = client.messages.create(**request)
        record_call(getattr(response, "model", None) or model, getattr(response, "usage", None),
                    source="text-fallback/tools")
        if getattr(response, "stop_reason", "") != "tool_use":
            text = _text(response)
            if getattr(response, "stop_reason", "") == "refusal":
                text = text or "I can't help with that one."
            if not text:
                raise RuntimeError("Claude returned an empty answer.")
            return {"text": text, "model": model, "provider": "claude",
                    "tools_ran": list(toolbox.ran)}
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            output = toolbox.run(block.name, dict(getattr(block, "input", None) or {}))
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": output[:8000]})
        messages.append({"role": "user", "content": results})
    # Out of steps: let the caller's text-only route answer instead.
    raise RuntimeError("Claude did not finish within the tool step limit.")
