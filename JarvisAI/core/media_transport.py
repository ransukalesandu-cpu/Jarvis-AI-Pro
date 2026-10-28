"""System media transport for the HUD's music task panel.

The glass music panel offers play/pause, previous and next. Those buttons have to
*do* something real, so they send the OS media keys — the same keys a keyboard's
play/pause button sends. Whatever is actually playing receives them: a browser
tab, Spotify, VLC, Windows Media Player.

Why not reuse ``actions/spotify_control.py``? That handler calls
``_ensure_spotify()`` first, which *launches Spotify* if it is not running. That
is right when the user asked for Spotify by name and wrong for a transport
button on a panel that may be showing a YouTube video — pressing pause must not
start an unrelated app.

Truthfulness rules
------------------
* No ``pyautogui`` means no transport: :func:`available` returns False, the HUD
  then draws no transport buttons at all rather than dead ones.
* :func:`send` returns ``(ok, detail)``. ``ok`` is only True when the key was
  actually delivered; the HUD flips the panel's play/pause glyph from that
  answer, never optimistically.
* Nothing here reports *what* is playing. The OS media keys are fire-and-forget,
  so the panel shows the state the caller already knows and never invents a
  track title.
"""

from __future__ import annotations

from typing import Callable

__all__ = ["COMMANDS", "available", "send", "command_for_action", "TransportController"]

#: Logical command → the OS media key that performs it.
COMMANDS = {
    "play_pause": "playpause",
    "next": "nexttrack",
    "previous": "prevtrack",
    "stop": "stop",
}


def _presser() -> Callable[[str], None] | None:
    """Return ``pyautogui.press`` when it is importable, else ``None``."""
    try:
        import pyautogui
    except Exception:
        return None
    press = getattr(pyautogui, "press", None)
    return press if callable(press) else None


def available() -> bool:
    """True when this machine can actually deliver a media key."""
    return _presser() is not None


def send(command: str, *, press: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Deliver one media key.

    ``press`` is injectable so tests never touch the real keyboard. Returns
    ``(ok, detail)``; ``detail`` is a short human sentence for a toast or log.
    """
    name = str(command or "").strip().lower()
    key = COMMANDS.get(name)
    if key is None:
        return False, f"Unknown media command: {command!r}"

    presser = press if press is not None else _presser()
    if presser is None:
        return False, "Media keys are unavailable (pyautogui is not installed)."

    try:
        presser(key)
    except Exception as exc:
        return False, f"The media key was rejected ({type(exc).__name__})."

    return True, {
        "play_pause": "Play/pause sent.",
        "next": "Skipped to the next track.",
        "previous": "Went back to the previous track.",
        "stop": "Playback stopped.",
    }[name]


def command_for_action(action_name: str) -> str | None:
    """Map a voice/tool action name to a transport command, if it is one."""
    name = str(action_name or "").strip().lower()
    if name in {"play_music", "spotify_control", "youtube_video", "music"}:
        return None
    return {
        "pause_music": "play_pause",
        "resume_music": "play_pause",
        "play_pause": "play_pause",
        "next_track": "next",
        "next_song": "next",
        "previous_track": "previous",
        "stop_music": "stop",
    }.get(name)


class TransportController:
    """State holder that turns panel button presses into real media keys.

    The panel's play/pause glyph is the only state this class changes, and it
    changes it *after* :func:`send` reports success — never optimistically. If
    there is no presser, :meth:`callbacks` returns ``{}`` and the panel draws no
    transport buttons at all.
    """

    def __init__(self, *, on_change: Callable[[bool], None] | None = None,
                 press: Callable[[str], None] | None = None,
                 playing: bool = False):
        self._on_change = on_change
        self._press = press
        self._playing = bool(playing)
        self.last_detail = ""

    @property
    def playing(self) -> bool:
        return self._playing

    def available(self) -> bool:
        return self._press is not None or _presser() is not None

    def _emit(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(self._playing)
        except Exception:
            # A dead HUD callback must not break the transport.
            return

    def dispatch(self, command: str) -> bool:
        ok, detail = send(command, press=self._press)
        self.last_detail = detail
        if ok and command == "play_pause":
            self._playing = not self._playing
            self._emit()
        return ok

    def play_pause(self) -> bool:
        return self.dispatch("play_pause")

    def next(self) -> bool:
        return self.dispatch("next")

    def previous(self) -> bool:
        return self.dispatch("previous")

    def callbacks(self) -> dict[str, Callable[[], None]]:
        """Keyword arguments for :class:`ui.task_panels.TaskSpec`.

        Empty when no media key can be delivered, which is what keeps the
        buttons from being drawn on a machine that cannot honour them.
        """
        if not self.available():
            return {}
        return {
            "on_play_pause": self.play_pause,
            "on_next": self.next,
            "on_previous": self.previous,
        }
