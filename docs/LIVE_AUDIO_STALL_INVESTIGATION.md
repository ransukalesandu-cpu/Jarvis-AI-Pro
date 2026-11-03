# Gemini Live: "JARVIS stops speaking mid-sentence"

Symptoms reported on the Windows laptop (`sounddevice` output): JARVIS may stop
speaking mid-sentence, stall during playback, or never finish a Gemini Live
answer. This note lists what the code shows, what was fixed, and what still
needs a test on the real hardware. Line numbers refer to the
`feature/hybrid-claude-brain` branch.

Files read: `JarvisAI/main.py` (Live loop), `core/live_audio.py`,
`core/audio_playback.py`, `core/playback_interrupt.py`, `core/barge_in.py`,
`core/echo.py`, `core/audio_callback_guard.py`, `core/live_session.py`,
`core/runtime/live_wake.py`.

## Candidate causes

| # | Cause | Where | Status |
|---|-------|-------|--------|
| 1 | **Interrupted answer replays after an aborted write.** When an interrupt aborts the device while `stream.write` is running, the write raises. That `except` branch cleared the interrupt flag but not the worker's private `pending_pcm`. After the stream restarted, the rest of the cancelled answer played, and `set_speaking(True)` kept the mic closed to Gemini, so the owner's next words could be lost. | `core/audio_playback.py:713-723` | **Fixed** + regression test (`test_playback_stall_fixes.py`, worker driven with a fake stream; fails without the fix). |
| 2 | **False barge-in skips words.** A VAD/echo barge-in is provisional (`core/barge_in.py`): it holds the answer and resumes it if Gemini does not confirm within 1.5 s. But the worker's private `pending_pcm` (up to ~600 ms) was discarded, not held, so the resumed answer jumped ahead. | `core/audio_playback.py:134` (`drop_pending_pcm`), call sites 305, 327, 390, 719 | **Fixed**: buffered words are prepended to the held answer. Audio already inside the device buffer (`output_stream.abort()`, `main.py:1361`) and the batch being written are still lost (about `stream.latency` + ≤100 ms). That can't be recovered without changing the abort design. |
| 3 | **Speaker switched mid-sentence by the pacing check.** After 1 s of PCM, if writes took < 20 % of the audio time, the worker decided the endpoint was silent and switched to another "tested" output device mid-reply. An idle stream's empty buffer absorbs `stream.latency` seconds instantly (300–500 ms is common on Windows, more on Bluetooth), so a healthy high-latency speaker could trip it. The rest of the answer then went to a different device. | `core/live_audio.py:298`, `core/audio_playback.py:625-644` | **Fixed**: the check now subtracts the device's reported latency and runs after `1 s + latency`. Truly unpaced endpoints are still detected (unit tests). Look for `WARNING: submitted ... attempting a tested speaker fallback` in old logs to see whether this ever fired. |
| 4 | **Self-confirming false barge-in.** On a provisional barge-in, `_interrupt_on_loop` sends the 1.5 s mic pre-roll to Gemini so the user's first words are not lost. If the local detector was fooled by echo, that pre-roll contains JARVIS's own voice. Gemini can transcribe it or raise `interrupted`, which confirms the barge-in and cancels the answer server-side. | `main.py:1391` (pre-roll), `core/runtime/live_wake.py:113`, confirmation at `main.py:2296` and the input-transcription branch | **Needs manual test.** Diagnostics: `barge_in_confirmed ... echo_overlap=` near 1.0 means it is happening. Not guess-fixed: dropping the pre-roll would cut the start of real interruptions. |
| 5 | **VAD/EchoGuard false triggers.** Two consecutive 64 ms mic blocks judged "user speech" (WebRTC VAD + `EchoGuard.is_user_speech(fast=True)`) pause playback. Laptop speakers next to the mic are the worst case. | `main.py:1902-1935`, `core/echo.py:208` | **Needs manual test.** Diagnostics: `interrupt provisional=True` lines without you speaking. |
| 6 | **Session closed by the server mid-answer.** The receive loop ignored `go_away` (advance notice that the Live connection will close). A close during a reply loses the remainder. Only an unanswered user request is retried, so a half-spoken answer is not. | `main.py:2211` | **Diagnostics only** (`go_away time_left=...`). Reconnect policy unchanged. |
| 7 | **Output underrun / slow device.** Live audio arrives in bursts; a dry queue re-arms a 150–600 ms prebuffer (audible pause) and is already logged as `Output underrun; rebuffering`. A blocking `stream.write` that never returns (device unplugged, Windows route change) stalls playback with no timeout. | `core/audio_playback.py:436-460`, `:595` | **Diagnostics**: `output_underflow` (PortAudio's own flag, previously ignored) and `slow_write`. No fix without evidence. |
| 8 | **Swallowed callback errors.** Mic callback failures are reported at most once per 30 s and the frame is dropped. | `core/audio_callback_guard.py:25` | Low likelihood for output stalls; existing `[AudioTrace 1/MIC] Callback failed` line is enough. |
| 9 | **Turn-complete handling.** The old "interrupted flag survives `turn_complete`" bug is already fixed (`core/barge_in.py` docstring, `main.py` turn-complete branch). No new defect found. One minor gap: the output transcript is not recorded while an answer is held, so a resumed answer's text can be missing from the log (cosmetic). | `main.py:2343` | No change. |

## Diagnostics flag

Set the flag before starting JARVIS, from the `JarvisAI` folder:

```bat
set JARVIS_AUDIO_DEBUG=1
python main.py > audio_debug.log 2>&1
```

Every event is one `[AudioDebug]` line with a monotonic timestamp. It contains
counts, sizes, timings and ratios only, never transcript text, audio or keys:

* `interrupt provisional=... queued_chunks=... device_buffer_ms=... preroll_frames=...`
* `playback_discard where=loop|prebuffer|write_aborted bytes=... held=...`
* `barge_in_confirmed by=server_interrupted|input_transcription held=... echo_overlap=...`
* `barge_in_released chunks=... held_ms=...`
* `output_underflow`, `slow_write write_ms=... batch_ms=...`
* `go_away time_left=... turn_pending=...`

## Manual test on the laptop

Use the laptop's built-in speakers and microphone (the worst echo case), at
normal volume, in a quiet room.

1. Start JARVIS with `JARVIS_AUDIO_DEBUG=1` as above.
2. **Long answer, no interruption:** ask "Tell me a two-minute story about a
   lighthouse." Do not speak. Expected: the answer finishes. If it stops, look
   at the lines just before the stop:
   * `interrupt provisional=True` → cause 5 (false VAD trigger). Then
     `barge_in_released` means it resumed (fixes 1/2 apply). `barge_in_confirmed`
     with `echo_overlap` ≥ 0.6 means cause 4.
   * `go_away` → cause 6.
   * `WARNING: submitted ... speaker fallback` → cause 3 (should no longer appear
     on a healthy device).
   * `slow_write` / `output_underflow` → cause 7.
   * Nothing at all → note the last `[AudioTrace ...]` line and report it.
3. **Real interruption:** during a long answer say "Hey Jarvis, stop" or start
   a new question. Expected: playback stops at once, no old words play
   afterwards (fix 1), and the new question is answered.
4. **Repeat step 2 with headphones.** If the problem disappears with
   headphones, the cause is echo (4/5), not the network or the device.
5. **Repeat step 2 on Bluetooth output**, if one is used. This is where cause 3
   was most likely.
6. Send `audio_debug.log` (it contains no transcript text) with the result of
   each step.
