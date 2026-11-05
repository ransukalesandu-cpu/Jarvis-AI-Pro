"""A featherweight stand-in for ``google.genai.types`` inside the laptop agent.

Laptop tools build Gemini requests with ``types.Part.from_bytes(...)`` and
friends, but the agent never talks to Gemini itself: core.gemini forwards the
request to the hub. Importing the real google-genai costs about 50 MB, half the
agent's budget, so the agent installs this shim first. It records what a tool
builds; core/gemini_wire.py serializes it; the hub rebuilds the real objects.

Set ``JARVIS_AGENT_REAL_GENAI=1`` to import the real library instead.
"""
from __future__ import annotations

import os
import sys
import types as _pytypes


class _Blob:
    def __init__(self, data=b"", mime_type=""):
        self.data, self.mime_type = data, mime_type


class Part:
    def __init__(self, text=None, inline_data=None, **kwargs):
        self.text, self.inline_data = text, inline_data
        self.extra = kwargs

    @classmethod
    def from_bytes(cls, data=b"", mime_type="", **_):
        return cls(inline_data=_Blob(data, mime_type))

    @classmethod
    def from_text(cls, text="", **_):
        return cls(text=text)


class _Record:
    """Any other types.X(...) call: keeps its keyword arguments."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self, exclude_none=True, mode="json"):
        return {k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in self.__dict__.items() if not (exclude_none and v is None)}


def install() -> bool:
    """Register the shim as google.genai.types unless the real one is wanted."""
    if os.environ.get("JARVIS_AGENT_REAL_GENAI") == "1" or "google.genai" in sys.modules:
        return False
    types_mod = _pytypes.ModuleType("google.genai.types")
    types_mod.Part = Part
    types_mod.Blob = _Blob
    types_mod.__getattr__ = lambda name: type(name, (_Record,), {})
    genai_mod = _pytypes.ModuleType("google.genai")
    genai_mod.types = types_mod

    def _no_client(*_a, **_k):
        raise RuntimeError("The laptop agent has no Gemini key; requests go through the hub.")
    genai_mod.Client = _no_client
    try:
        import google
    except ImportError:
        google = _pytypes.ModuleType("google")
        google.__path__ = []
        sys.modules["google"] = google
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod
    google.genai = genai_mod
    return True
