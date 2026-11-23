"""'Form a heart' / 'write JARVIS' — the web UI's neural brain flows into a shape and back."""
from __future__ import annotations

from jarvis.core import brain_shapes


def form_shape(parameters: dict, **_ctx) -> str:
    p = parameters or {}
    shape, text = str(p.get("shape") or ""), str(p.get("text") or "")
    sent = brain_shapes.request(shape, text)
    if sent is None:
        if str(shape).strip().lower() == "text" or text:
            return f"I can only write up to {brain_shapes.TEXT_MAX} plain letters or digits."
        return "I can form: " + ", ".join(s for s in brain_shapes.SHAPES if s != "brain") + ", or go back to the brain."
    if sent[0] == "brain":
        return "Back to the brain."
    return f"Forming '{sent[1]}'." if sent[0] == "text" else f"Forming a {sent[0]}."


TOOL = {
    "name": "form_shape",
    "description": (
        "Make the neural brain in the centre of the web UI flow into a shape for a few seconds, then "
        "return. Shapes: sphere, cube, torus, helix (DNA), heart, globe, star, or text (up to 16 "
        "letters/digits, e.g. a name or 'JARVIS'); 'brain' returns at once. Use for 'turn into a "
        "heart', 'show a DNA helix', 'write my name', 'become a globe', 'back to the brain'. Works only "
        "in the web UI with the neural brain."),
    "parameters": {"type": "OBJECT", "properties": {
        "shape": {"type": "STRING", "description": "sphere | cube | torus | helix | heart | globe | star | text | brain"},
        "text": {"type": "STRING", "description": "only for shape=text: up to 16 letters/digits"},
    }, "required": ["shape"]},
    "handler": form_shape,
    "risk": "read",
    "timeout": 5,
}
