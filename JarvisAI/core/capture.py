"""On-demand screen capture (mss + Pillow, no opencv).

Used by ``see_screen`` (Module 4) and the ``ui_automate`` loop (Module 3).
Nothing here runs continuously: each call grabs one frame and returns it.
"""
from __future__ import annotations

import io
from dataclasses import dataclass


@dataclass
class Frame:
    jpeg: bytes
    width: int            # size of the JPEG we send to the model
    height: int
    left: int = 0         # where the captured area sits on the virtual screen
    top: int = 0
    scale: float = 1.0    # captured pixels per JPEG pixel

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Map a point in the JPEG back to real screen coordinates."""
        return int(self.left + x * self.scale), int(self.top + y * self.scale)


def _window_box(title: str) -> dict | None:
    """Bounding box of the first visible window whose title contains ``title``."""
    try:
        import pygetwindow as gw
    except Exception:
        return None
    needle = title.strip().lower()
    for win in gw.getAllWindows():
        if needle in (win.title or "").lower() and win.width > 40 and win.height > 40:
            try:
                if getattr(win, "isMinimized", False):
                    win.restore()
                win.activate()
            except Exception as exc:
                print(f"[capture] could not focus window: {exc}")
            return {"left": int(win.left), "top": int(win.top),
                    "width": int(win.width), "height": int(win.height)}
    return None


def grab_screen(window: str = "", *, monitor: int = 1, max_side: int = 1600,
                quality: int = 80) -> Frame:
    """One screenshot of a monitor (1 = primary, 0 = all) or of one window."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        box = _window_box(window) if window else None
        if box is None:
            if window:
                raise LookupError(f"no open window matches '{window}'")
            monitors = sct.monitors
            box = dict(monitors[monitor if 0 <= monitor < len(monitors) else 1])
        shot = sct.grab(box)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    scale = 1.0
    longest = max(img.size)
    if longest > max_side:
        scale = longest / max_side
        img = img.resize((int(img.width / scale), int(img.height / scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return Frame(jpeg=buf.getvalue(), width=img.width, height=img.height,
                 left=int(box.get("left", 0)), top=int(box.get("top", 0)), scale=scale)
