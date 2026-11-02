"""Provisional local barge-in: pause JARVIS at once, discard only when confirmed.

Why this exists
---------------
While JARVIS is speaking, the microphone is not streamed to Gemini (that would
send JARVIS's own voice back). Local barge-in therefore relies on WebRTC VAD
plus :class:`core.echo.EchoGuard` to decide that the person, not the speaker,
is talking. On a laptop with built-in speakers and microphone that decision is
sometimes wrong: echo is classified as the user.

Before this module, a local barge-in *discarded* the rest of the answer and set
``JarvisLive._interrupted``, which made the receiver drop every further audio
chunk. The server was never told, so it kept generating an answer nobody could
hear. When the cut-off answer was a tool follow-up or a turn JARVIS had injected
itself (no user transcript in that turn), the flag also survived the turn's
``turn_complete`` and silenced the *next* response too, until the owner spoke
again. That is the "stops mid-sentence / never finishes the answer" bug.

Now a VAD/echo barge-in stops playback immediately (the user hears silence
within one playback slice) but keeps the remaining PCM here. The interruption
is *confirmed* when Gemini reports ``interrupted`` or transcribes user speech;
the held audio is then dropped. If neither arrives within
:data:`CONFIRM_WINDOW_SECONDS`, it was a false alarm and the held audio is
released back to the speaker queue, so the answer finishes.

Explicit interruptions (wake word, stop word, UI button) are not provisional.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: How long to wait for Gemini to confirm user speech before resuming.
#: Gemini Live normally reports `interrupted` or an input transcription well
#: under a second after the user starts talking.
CONFIRM_WINDOW_SECONDS = 1.5


@dataclass
class HeldAudio:
    """PCM withheld from the speaker while a local barge-in is unconfirmed."""

    active: bool = False
    token: int = 0
    chunks: list[bytes] = field(default_factory=list)
    turn_complete: bool = False

    def begin(self, already_queued: list[bytes]) -> int:
        """Start holding; ``already_queued`` is the speaker queue's content."""
        self.token += 1
        self.active = True
        self.chunks = [bytes(c) for c in already_queued if c]
        self.turn_complete = False
        return self.token

    def hold(self, pcm: bytes) -> None:
        if self.active and pcm:
            self.chunks.append(bytes(pcm))

    def mark_turn_complete(self) -> None:
        if self.active:
            self.turn_complete = True

    def confirm(self) -> None:
        """The user really is speaking: the held answer is cancelled."""
        self.active = False
        self.chunks = []
        self.turn_complete = False

    def release(self, token: int) -> tuple[list[bytes], bool] | None:
        """End a false alarm. Returns (chunks, turn_complete) or None if stale."""
        if not self.active or token != self.token:
            return None
        chunks, done = self.chunks, self.turn_complete
        self.active = False
        self.chunks = []
        self.turn_complete = False
        return chunks, done

    @property
    def held_ms(self) -> float:
        return sum(len(c) for c in self.chunks) / (24000 * 2) * 1000
