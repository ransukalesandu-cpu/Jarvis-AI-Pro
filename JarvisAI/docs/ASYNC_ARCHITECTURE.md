# Async Runtime Architecture

This document describes the current runtime boundaries and the rules for extending them safely.

## Runtime ownership

- **Qt/UI thread:** owns QApplication, widgets, HUD updates, and Qt signals.
- **JARVIS asyncio thread:** `main()` starts a dedicated non-daemon worker thread; that worker calls `asyncio.run(jarvis.run())`. The asyncio loop owns the Gemini Live session, session-scoped tasks, asyncio queues/events, reconnects, and shutdown coordination.
- **Audio callbacks and background workers:** audio callbacks must stay short and must not directly manipulate Qt widgets or use asyncio queues as if they were thread-safe. Cross-thread handoffs must use a thread-safe loop API or a thread-safe queue. Voice barge-in uses WebRTC VAD as a speech/noise gate, then EchoGuard to reject the assistant's own speaker echo.
- **Blocking operations:** use `asyncio.get_running_loop().run_in_executor(...)` (or `asyncio.to_thread` where compatible) for blocking work that would otherwise stall Live audio/session tasks.

## Rules for async code

1. Inside a coroutine or callback running on the event-loop thread, use `asyncio.get_running_loop()`. It fails fast if there is no running loop instead of returning a loop that may not be running or may belong to another thread.
2. From another thread, do not call `asyncio.create_task()`, set an `asyncio.Event` directly, or access an `asyncio.Queue` directly. Use `asyncio.run_coroutine_threadsafe(coro, loop)` for a coroutine and `loop.call_soon_threadsafe(callback, ...)` for a small callback.
3. Keep all Qt widget updates on the Qt thread. Use Qt signals or the UI's existing thread-safe dispatch mechanism when reporting background work.
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
