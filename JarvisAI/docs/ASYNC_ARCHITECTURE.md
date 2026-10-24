# Async Runtime Architecture

This document describes the current runtime boundaries and the rules for extending them safely.

## Runtime ownership

- **Qt/UI thread:** owns QApplication, widgets, HUD updates, and Qt signals.
- **JARVIS asyncio thread:** `main()` starts a dedicated non-daemon worker thread; that worker calls `asyncio.run(jarvis.run())`. The asyncio loop owns the Gemini Live session, session-scoped tasks, asyncio queues/events, reconnects, and shutdown coordination.
- **Audio callbacks and background workers:** audio callbacks must stay short and must not directly manipulate Qt widgets or use asyncio queues as if they were thread-safe. Cross-thread handoffs must use a thread-safe loop API or a thread-safe queue. Voice barge-in uses WebRTC VAD as a speech/noise gate, then EchoGuard to reject the assistant's own speaker echo.
- **Blocking operations:** use `asyncio.get_running_loop().run_in_executor(...)` (or `asyncio.to_thread` where compatible) for blocking work that would otherwise stall Live audio/session tasks.

## Rules for async code

1. Inside a coroutine or callback running on the event-loop thread, use `asyncio.get_running_loop()`. It fails fast if there is no running loop instead of returning a loop that may not be running or may belong to another thread.
2. From another thread, do not call `asyncio.create_task()`, set an `asyncio.Event` directly, or access an `asyncio.Queue` directly. Use `asyncio.run_coroutine_threadsafe(coro, loop)` for a coroutine and `loop.call_soon_threadsafe(callback, ...)` for a small callback. The sounddevice microphone callback must hand barge-in state changes to the session loop instead of draining asyncio queues directly.
3. Keep all Qt widget/canvas mutations on the Qt thread. Audio workers must submit HUD waveform levels and mouth-animation (viseme) schedules through Qt signals; wrappers must not directly mutate `HudCanvas` state from an audio or asyncio thread.
4. Treat cancellation and shutdown as normal lifecycle events. Stop accepting work, signal the loop, allow session tasks to unwind, then close the loop. Do not block the event-loop thread waiting for a future submitted to that same loop.
5. Keep microphone callbacks lightweight: no network calls, long computations, blocking waits, or UI operations in the callback.
6. When adding a task to a session, make its ownership clear. Prefer the existing session `asyncio.TaskGroup` for tasks that should end when the Live session ends; use explicitly tracked tasks for longer-lived work and cancel/await them during shutdown.
7. For voice interruption, confirm speech with 20 ms WebRTC VAD frames (when the optional module is available), then apply EchoGuard and its sustained-evidence rule. On confirmation, signal the event loop, abort the output device buffer, drain queued audio, and resume the stream before the next response. Keep the existing local wake-word interrupt as a separate trusted path.

## Initial hardening in this change

The async methods in `JarvisAI/main.py` now call `asyncio.get_running_loop()` rather than `asyncio.get_event_loop()`. This makes the intended event-loop ownership explicit and avoids accidentally retrieving a non-running or thread-local loop from async code.

## Validation checklist

- Start the app and confirm the HUD opens.
- Confirm Gemini Live connects and microphone input is streamed.
- Trigger a tool that runs blocking work and verify the UI remains responsive.
- Test manual interruption, voice barge-in over speaker output, false triggers from fan/hum noise, reconnect, and orderly shutdown.
- Test on the target Windows/Python version; static inspection alone does not prove device-specific audio behavior.


## Diagnosing a silent voice pipeline

The runtime prints one-time-per-turn checkpoints with the `[AudioTrace ...]` prefix. Read them in order:

- `1/MIC`: the input stream opened and the callback received actual samples. If the stream-open line appears but the first callback does not, inspect the selected microphone, OS permissions, and PortAudio/device state.
- `1→3`: the sender took a microphone/phone frame and sent it to Gemini Live. If mic callbacks work but no frame is sent, check whether JARVIS is asleep, muted, in push-to-talk mode without the key held, or routing input through the phone.
- `3/LIVE`: at least one server event arrived. `2/STT` logs the first user transcription for a turn; `3/GEN` logs the first accepted assistant transcription; `3→4/AUDIO` logs returned PCM audio.
- `4/OUTPUT`: the playback stream opened, a PCM chunk reached its queue, and the first `sounddevice.write` started/returned. A returned write means PortAudio accepted the buffer, not that audible sound was confirmed.
- `Callback failed`, `Live audio send failed`, `Speaker write failed`, or `CRITICAL THREAD CRASH` includes exception details and/or a traceback to identify the failing stage.

If a turn completes with assistant text but no PCM audio payload, the trace explicitly reports that mismatch. Do not add `pyttsx3`/COM or `PyAudio` code to this path unless the app is deliberately changed to use those engines; this runtime uses Gemini Live native audio and `sounddevice`.


### Tiny PCM payloads and silent output

Gemini Live native audio is 24 kHz, mono, signed 16-bit PCM in this application. A 2-byte payload is only one sample, not a spoken phrase. The receive loop buffers sub-10 ms fragments until at least 480 bytes (10 ms) are available, keeps 16-bit sample alignment, and only then queues PCM for playback. At turn completion, any incomplete remainder is discarded and the log distinguishes text-without-playable-audio from a fully missing audio payload.


### Preventing false barge-in before playback starts

Voice-based interruption is armed only after JARVIS is actually speaking and the echo guard has a recent playback reference. While Gemini is generating the first response audio, the microphone still feeds the local wake-word detector, but VAD/echo-based interruption evidence is cleared rather than allowed to cancel a not-yet-audible greeting. This avoids treating a clap or background noise as user speech when EchoGuard has no output PCM to compare against. Real-hardware testing is still required to tune acoustic interruption behavior.
