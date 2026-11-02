"""Make an image, video or advert through a pluggable provider (background job).

Demo: "look at this product and make a short ad" -> one camera frame, Gemini
writes a headline and tagline from it, the media provider renders the ad, and
the file opens when it is ready. See core/media_generation.py for providers.
"""
from __future__ import annotations

from core.media_generation import MediaRequest, provider_for


def _copy_from_photo(image: bytes | None, brief: str) -> tuple[str, str]:
    """Ask Gemini for ad copy. Falls back to the brief when unavailable."""
    try:
        from google.genai import types as gtypes

        from core import gemini
        parts = []
        if image:
            parts.append(gtypes.Part.from_bytes(data=image, mime_type="image/jpeg"))
        parts.append(
            "Write advert copy for the product in this photo. Brief: " + (brief or "short ad")
            + '\nReply only with JSON: {"headline": "max 6 words", "tagline": "max 14 words"}')
        reply = gemini.as_json(parts, tier=gemini.FAST, timeout_ms=30_000, default={}) or {}
        return str(reply.get("headline") or brief), str(reply.get("tagline") or "")
    except Exception as exc:
        print(f"[generate_media] copywriting unavailable: {exc}")
        return brief, ""


def generate_media(parameters: dict, cancel_event=None, **_ctx) -> str:
    p = parameters or {}
    kind = str(p.get("kind") or "image").strip().lower()
    prompt = str(p.get("prompt") or "").strip()
    provider = provider_for(kind)
    if provider is None:
        return (f"No {kind} generation provider is configured. Add one as a plugin "
                "(see core/media_generation.py).")
    image = None
    source = str(p.get("source") or "").strip().lower()
    if source == "camera":
        from core.camera_snapshot import capture_frame
        image = capture_frame()
    elif source == "screen":
        from core.capture import grab_screen
        image = grab_screen().jpeg
    headline, tagline = str(p.get("headline") or ""), str(p.get("tagline") or "")
    if kind == "ad" and not headline:
        headline, tagline = _copy_from_photo(image, prompt)
    result = provider.generate(MediaRequest(kind=kind, prompt=prompt, reference_image=image,
                                            headline=headline, tagline=tagline,
                                            cancel_event=cancel_event))
    if result.files and p.get("open_when_done", True):
        try:
            from core.pc_control import open_target
            open_target(result.files[0])
        except Exception as exc:
            print(f"[generate_media] could not open result: {exc}")
    note = f" {result.note}" if result.note else ""
    return f"Made {kind} with {result.provider}: {', '.join(result.files)}.{note}"


TOOL = {
    "name": "generate_media",
    "description": (
        "Create an image, video or advert in the background. kind = image | video | ad; "
        "prompt = what to make; source = camera or screen to start from a fresh "
        "photo (e.g. a product the owner holds up). The result opens when ready."),
    "parameters": {"type": "OBJECT", "properties": {
        "kind": {"type": "STRING", "description": "image | video | ad"},
        "prompt": {"type": "STRING"},
        "source": {"type": "STRING", "description": "camera | screen | none"},
        "headline": {"type": "STRING"},
        "tagline": {"type": "STRING"},
        "open_when_done": {"type": "BOOLEAN"},
    }, "required": ["kind"]},
    "handler": generate_media,
    "risk": "write",
    "long_running": True,
}
