"""System/background monitors, proactive mode, phone relay and dashboard.

Part of ``JarvisLive`` (JarvisAI/main.py), which inherits this mixin. The
methods were moved here verbatim; they run with ``self`` bound to the live
session object, so every attribute they use is set up in ``JarvisLive.__init__``.
"""


import asyncio
import time
from actions.background_monitor import check_all as monitor_check_all, list_monitors
from core import security
from memory.config_manager import get_memory_provider_access_enabled, get_quiet_hours
from memory.memory_manager import load_memory

#: The owner must have been silent this long before JARVIS starts a turn.
PROACTIVE_USER_QUIET_SECONDS = 4.0
TRIGGER_TICK_SECONDS = 5.0


class BackgroundServicesMixin:
    """System/background monitors, proactive mode, phone relay and dashboard."""

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while not self._shutdown_requested:
            await asyncio.sleep(10)
            if self._shutdown_requested:
                return
            try:
                alert = await asyncio.to_thread(self._sys_monitor.check)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._shutdown_requested:
                    return
                print(f"[Monitor] ⚠️ System monitor check failed: {exc}")
                continue
            if self._shutdown_requested:
                return
            if not alert or not self.session or not self._awake:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": alert}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while not self._shutdown_requested:
            if self.session and self._awake:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            print("[JARVIS] Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session or not self._awake:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                memory_access = get_memory_provider_access_enabled()
                if not get_memory_provider_access_enabled():
                    memory = {}
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = (
                    self._session_log[-8:]
                    if get_memory_provider_access_enabled() and self._session_log else []
                )
                project_state = " ".join(
                    " ".join(str(state.get(key, "")) for key in ("name", "status", "current_state", "last_outcome"))
                    for state in (memory.get("project_states", {}) or {}).values() if isinstance(state, dict)
                ) if memory_access else ""
                planning_event = "\n".join(recent_turns[-6:]) if recent_turns else "idle_checkin"
                planner_suggestions = self._proactive_planner.plan(
                    authorized_event=memory_access, event=planning_event, project_state=project_state)
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                    planned_suggestions = planner_suggestions or None,
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                print("[JARVIS] Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Proactive triggers (core/triggers.py) ────────────────────────────────

    def _proactive_turn_blocker(self) -> str:
        """Why JARVIS may not start a turn right now ('' means it may).

        Never talk over the owner: no injected turn while they are speaking or
        have just spoken, while JARVIS is speaking, or while a turn is pending.
        """
        if not self.session:
            return "no live session"
        with self._speaking_lock:
            if self._is_speaking:
                return "jarvis speaking"
        if self._assistant_turn_pending or self._briefing_active:
            return "turn pending"
        if self._interrupted:
            return "interruption in progress"
        if getattr(self, "_inflight_user_text", ""):
            return "owner turn in progress"
        if time.monotonic() - self._last_user_speech < PROACTIVE_USER_QUIET_SECONDS:
            return "owner spoke recently"
        if getattr(self, "_turn_done_event", None) is not None and self._turn_done_event.is_set():
            return "playback finishing"
        return ""

    async def _fire_trigger(self, trigger, prompt: str) -> None:
        text = (
            f"[Automatic trigger '{trigger.name}' — this is JARVIS's own scheduler, "
            "not the owner speaking. Speak to the owner now.] " + prompt
        )
        if not self._awake:
            self.wake(reason=f"trigger {trigger.name}")
        await self.session.send_client_content(
            turns={"role": "user", "parts": [{"text": text}]},
            turn_complete=True,
        )
        self.ui.write_log(f"SYS: Trigger '{trigger.name}' fired.")
        print(f"[Triggers] Fired {trigger.name}.")

    async def _run_trigger_scheduler(self) -> None:
        """Background task: inject due triggers as turns so JARVIS speaks first."""
        from core.triggers import get_trigger_registry
        registry = get_trigger_registry()
        while not self._shutdown_requested:
            await asyncio.sleep(TRIGGER_TICK_SECONDS)
            try:
                due = registry.due(quiet_hours=get_quiet_hours())
                if not due:
                    continue
                if self._proactive_turn_blocker():
                    continue      # still due; retried on the next tick
                trigger, prompt = due[0]          # one turn at a time
                registry.mark_fired(trigger.name)
                await self._fire_trigger(trigger, prompt)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[Triggers] Scheduler error: {type(exc).__name__}: {exc}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM; the phone sends only after BLE says PC is far."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                packet = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if self._phone_active and time.monotonic() - self._phone_last_audio_at > 2.0:
                    self._phone_active = False
                    self.ui.write_log("SYS: Phone audio stopped; audio returned to this PC.")
                continue
            if not self._phone_active:
                self._phone_active = True
                self._phone_route_offline_logged = False
                self.ui.write_log("SYS: BLE proximity changed to out of range; conversation transferred to phone.")
            self._phone_last_audio_at = time.monotonic()
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(packet)
                except asyncio.QueueFull:
                    pass

    def _phone_handoff_status(self) -> dict:
        beacon = self._phone_beacon
        return {
            "detection": "bluetooth-rssi" if beacon and beacon.enabled else "unavailable",
            "beaconEnabled": bool(beacon and beacon.enabled),
            "beaconUuid": beacon.service_uuid if beacon and beacon.enabled else "",
            "phoneRouteActive": self._phone_active,
        }

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while not self._shutdown_requested:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                manager = security.get_auth_manager()
                if manager.is_privacy_lock_active():
                    continue
                if manager.needs_pin():
                    # Credential text from a paired dashboard is checked locally and
                    # is never sent to Gemini or written to logs/history.
                    accepted = manager.verify_pin(str(text).strip())
                    if accepted:
                        self._interrupted = False
                        self._queue_auth_state_broadcast()
                    elif not manager.is_privacy_lock_active() and self._dashboard is not None:
                        await self._dashboard.broadcast({
                            "type": "auth_state",
                            "state": "pin_required",
                            "owner_verified": False,
                            "pin_required": True,
                            "privacy_lock_active": False,
                            "message": "Owner PIN/password was not accepted.",
                        })
                    continue
                if manager.is_silent():
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    # A remote command is deliberate control and the phone user
                    # has no desktop WAKE button — so it wakes JARVIS if asleep.
                    if not self._awake:
                        self.wake(reason="remote command")
                    security.mark_user_turn_started()
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    async def _stop_dashboard(self) -> None:
        """Stop dashboard listeners and relay tasks before the asyncio loop closes."""
        dashboard = self._dashboard
        if dashboard is not None:
            try:
                await dashboard.shutdown()
            except Exception as exc:
                print(f"[Dashboard] Graceful shutdown failed: {type(exc).__name__}.")

        command_task = self._dashboard_command_task
        if command_task is not None:
            if not command_task.done():
                command_task.cancel()
            await asyncio.gather(command_task, return_exceptions=True)
            self._dashboard_command_task = None

        dashboard_task = self._dashboard_task
        if dashboard_task is not None:
            await asyncio.gather(dashboard_task, return_exceptions=True)
            self._dashboard_task = None
