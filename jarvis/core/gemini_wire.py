"""Serialize a core.gemini.call() request so the laptop agent can ask the hub.

Contents are a list of strings and parts (``types.Part.from_bytes`` images,
text parts). On the wire every item becomes {"text": ...} or
{"inline_data": {"mime_type": ..., "data": base64}}. The config, when given,
becomes a plain dict. ``decode`` rebuilds real google-genai objects on the hub.
"""
from __future__ import annotations

import base64


def _part_to_wire(item) -> dict:
    if isinstance(item, str):
        return {"text": item}
    if isinstance(item, dict):
        if "inline_data" in item:
            blob = item["inline_data"]
            data = blob.get("data", b"")
            if isinstance(data, (bytes, bytearray)):
                data = base64.b64encode(bytes(data)).decode("ascii")
            return {"inline_data": {"mime_type": blob.get("mime_type", ""), "data": data}}
        return item
    blob = getattr(item, "inline_data", None)
    if blob is not None:
        return {"inline_data": {"mime_type": getattr(blob, "mime_type", ""),
                                "data": base64.b64encode(bytes(getattr(blob, "data", b""))).decode("ascii")}}
    text = getattr(item, "text", None)
    if text is not None:
        return {"text": str(text)}
    return {"text": str(item)}


def encode(contents, config=None) -> dict:
    items = contents if isinstance(contents, (list, tuple)) else [contents]
    wire_config = None
    if config is not None:
        dump = getattr(config, "model_dump", None)
        wire_config = dump(exclude_none=True, mode="json") if callable(dump) else dict(config)
    return {"contents": [_part_to_wire(i) for i in items], "config": wire_config}


def decode(payload: dict):
    from google.genai import types
    parts = []
    for item in payload.get("contents") or []:
        if "inline_data" in item:
            blob = item["inline_data"]
            parts.append(types.Part.from_bytes(data=base64.b64decode(blob.get("data", "")),
                                               mime_type=blob.get("mime_type") or "application/octet-stream"))
        else:
            parts.append(str(item.get("text", "")))
    config = payload.get("config")
    if config:
        config = types.GenerateContentConfig(**config)
    return parts, config
