"""Application wiring for the autonomous engine.

Everything that touches the rest of JARVIS lives here, so the engine itself stays
dependency-free and testable:

* configuration        → :mod:`agent.settings`
* owner authorization  → ``core.security`` (unchanged)
* consequential approval → ``core.confirm`` (the existing HUD/voice banner)
* screen capture / vision / desktop control → the modules in this package
* planning model       → ``core.hybrid_llm_router`` (the existing provider chain)
* voice output         → the caller's ``speak`` callable, via ``agent.voice``
* UI                   → the event bus; no widget is imported here

The service is a process-wide singleton because the app has exactly one
microphone, one HUD and one task queue. ``reset_service()`` exists for tests.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from jarvis.agent.accessibility import AccessibilityBridge
from jarvis.agent.computer_use import ComputerUseConfig, ComputerUseController, PyAutoGUIBackend
from jarvis.agent.events import AgentEvent, EventBus
from jarvis.agent.executor import StepExecutor
from jarvis.agent.models import Task, TaskState, TaskStep
from jarvis.agent.planner import TaskPlanner
from jarvis.agent.policy import ExecutionPolicy, PolicyEngine, Risk
from jarvis.agent.runner import RunnerConfig, TaskRunner
from jarvis.agent.screen_capture import ScreenCapture
from jarvis.agent.screen_vision import OcrEngine, ScreenVision
from jarvis.agent.settings import AgentSettings
from jarvis.agent.store import redact
from jarvis.agent.cloud_store import CloudTaskStore
from jarvis.agent.voice import SpeechAnnouncer, VoiceCommandRouter, status_sentence

from jarvis.core import failsoft
from jarvis.core.browser_automation import BrowserAutomation

logger = logging.getLogger("Jarvis.Agent")

_SERVICE: "AgentService | None" = None
_SERVICE_LOCK = threading.Lock()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


class AgentService:
    """Process-wide facade used by the voice tool, the HUD and tests."""

    def __init__(
        self,
        *,
        settings: AgentSettings | None = None,
        workspace: Path | str | None = None,
        store: Any | None = None,
        bus: EventBus | None = None,
        capture: ScreenCapture | None = None,
        vision: ScreenVision | None = None,
        computer: ComputerUseController | None = None,
        planner: TaskPlanner | None = None,
        ask_model: Callable[[str], str] | None = None,
        logger_: Callable[[str], None] | None = None,
    ):
        self.settings = settings or AgentSettings.load()
        self.workspace = Path(workspace).resolve() if workspace else _repo_root()
        self.bus = bus or EventBus()
        self.store = store if store is not None else CloudTaskStore()
        self._log = logger_ or (lambda message: logger.info("%s", message))
        self._announcer = SpeechAnnouncer(enabled=self.settings.autonomy_voice_updates)
        self._router = VoiceCommandRouter()
        self._lock = threading.RLock()
        self._started_lock = threading.Lock()
        self._speak: Callable[[str], None] | None = None

        self.capture = capture or ScreenCapture(
            monitor=1, max_width=1280, max_height=720, min_interval_s=2.0
        )
        self._manual_screen_paused = bool(self.settings.screen_paused)
        self.capture.set_paused(self._manual_screen_paused)

        self.vision = vision or ScreenVision(
            self.capture,
            ocr=OcrEngine(),
            accessibility=AccessibilityBridge(),
            logger_=self._log,
        )
        self.computer = computer or ComputerUseController(
            PyAutoGUIBackend(),
            vision=self.vision,
            config=ComputerUseConfig(
                dry_run=self.settings.dry_run,
                allow_clicks=self.settings.allow_desktop,
                allow_typing=self.settings.allow_desktop,
            ),
            authorize=self._authorize_desktop,
            logger=self._log,
        )
        # A separate visible Chromium context; never reuse the owner's personal browser profile.
        self.browser = BrowserAutomation(timeout_ms=15000)
        self._planner = planner or TaskPlanner(
            ask=ask_model if ask_model is not None else self._model_asker(),
            workspace=self.workspace,
            max_steps=self.settings.max_steps,
        )
        self.engine = PolicyEngine(
            ExecutionPolicy(
                allowed_risk=Risk.CONSEQUENTIAL,
                allow_shell=self.settings.allow_shell,
                allow_file_write=self.settings.allow_files,
                allow_input_control=self.settings.allow_desktop,
                workspace_root=str(self.workspace),
                max_runtime_s=self.settings.max_runtime_s,
                retry_budget=self.settings.retry_budget,
                max_steps=self.settings.max_steps,
            ),
            owner_check=self._owner_authorized,
        )
        self.runner = TaskRunner(
            store=self.store,
            planner=self._planner,
            executor=StepExecutor(engine=self.engine),
            policy_engine=self.engine,
            bus=self.bus,
            config=RunnerConfig(
                max_runtime_s=self.settings.max_runtime_s,
                retry_budget=self.settings.retry_budget,
                max_steps=self.settings.max_steps,
            ),
            workspace=self.workspace,
            vision=self.vision,
            computer=self.computer,
            browser=self.browser,
            request_approval=self._request_approval,
            before_step=self._authorize_task_step,
            on_milestone=self._on_milestone,
            logger=self._log,
        )
        self._last_task_snapshot: Task | None = None
        self._history_refresh_lock = threading.Lock()
        self._history_refresh_started = False
        self.bus.subscribe(self._on_event)

    # ── lifecycle ─────────────────────────────────────────────────────────
    def shutdown(self) -> None:
        try:
            self.runner.shutdown()
        except Exception:
            failsoft.suppress("agent.integration:shutdown")
        try:
            self.capture.close()
        except Exception:
            failsoft.suppress("agent.integration:shutdown")

    def attach_speaker(self, speak: Callable[[str], None] | None) -> None:
        """Give the agent the voice layer's speak function (from the tool ctx)."""
        self._speak = speak
        self._announcer.attach(speak)

    def subscribe(self, callback: Callable[[AgentEvent], None]) -> Callable[[], None]:
        return self.bus.subscribe(callback)

    # ── commands ──────────────────────────────────────────────────────────
    def start(self, objective: str, *, criteria: list[str] | None = None,
              source: str = "voice") -> Task:
        text = str(objective or "").strip()
        if not text:
            raise ValueError("Tell me what to work on.")
        if not self.settings.enabled:
            raise PermissionError("Autonomous tasks are switched off in settings.")
        if self._privacy_locked():
            raise PermissionError("Privacy Lock is active. Autonomous work is blocked.")
        if not self._owner_authorized():
            raise PermissionError(
                "Owner verification is required before starting an autonomous task."
            )
        task = self.runner.start(text, criteria=criteria, source=source)
        with self._lock:
            self._last_task_id = task.id
            self._last_task_snapshot = task
        return task

    def stop(self, reason: str = "Stopped by the owner.") -> bool:
        return self.runner.cancel(reason)

    def pause(self) -> bool:
        return self.runner.pause()

    def resume(self) -> bool:
        self._ensure_can_continue()
        return self.runner.resume()

    def resume_last(self) -> Task | None:
        """Continue the most recent unfinished task after rechecking access."""
        candidates = self.store.unfinished()
        if not candidates:
            return None
        self._ensure_can_continue()
        task = self.runner.resume_task(candidates[0].id)
        with self._lock:
            self._last_task_id = task.id
            self._last_task_snapshot = task
        return task

    def handle_voice(self, text: str) -> str | None:
        """Handle a bare voice sentence. Returns a reply, or None if unrelated."""
        command = self._router.parse(text)
        if command is None:
            return None
        if command.action == "stop":
            return "Stopping the task." if self.stop() else "Nothing is running to stop."
        if command.action == "pause":
            return "Paused." if self.pause() else "Nothing is running to pause."
        if command.action == "resume":
            try:
                if self.resume():
                    return "Continuing."
                return ("Resumed the last unfinished task." if self.resume_last()
                        else "There is nothing to resume.")
            except PermissionError as exc:
                return str(exc)
        if command.action == "status":
            return self.status_sentence()
        if command.action == "report":
            return self.report_text() or "There is no task report yet."
        if command.action == "run":
            try:
                task = self.start(command.objective, criteria=command.criteria)
            except (PermissionError, ValueError, RuntimeError) as exc:
                return str(exc)
            return (f"On it. I've queued a {len(task.steps) or 'new'} step task; "
                    "I'll report back when it matters.")
        return None

    # ── status ────────────────────────────────────────────────────────────
    def status_sentence(self) -> str:
        task = self.runner.active_task or self._latest_task()
        return status_sentence(task)

    def status(self) -> dict[str, Any]:
        state = self.runner.status()
        task = self.runner.active_task or self._cached_latest_task()
        self._schedule_history_refresh()
        state["task"] = task.to_dict() if task else None
        state["settings"] = self.settings.as_dict()
        state["capabilities"] = self.capabilities()
        state["storage_backend"] = str(getattr(self.store, "root", "injected"))
        return state

    def capabilities(self) -> dict[str, Any]:
        try:
            vision = self.vision.capabilities()
        except Exception as exc:  # never let a capability probe raise
            vision = {"error": redact(exc, 200)}
        configured = self._model_asker() is not None
        return {
            **vision,
            "desktop_control": bool(self.computer.available()),
            "planning_model": configured,
            "owner_authorized": self._owner_authorized(),
            "privacy_locked": self._privacy_locked(),
            "autonomy_enabled": self.settings.enabled,
        }

    def report_text(self) -> str:
        task = self.runner.active_task or self._latest_task()
        if task is None or task.report is None:
            return ""
        return task.report.as_text()

    def latest_report(self) -> dict[str, Any] | None:
        task = self._latest_task()
        return task.report.to_dict() if task and task.report else None

    # ── reusable workflows ------------------------------------------------
    def _workflow_library(self):
        """Load the small workflow library only when a workflow feature is used."""
        library = getattr(self, "_workflow_library_instance", None)
        if library is None:
            from jarvis.agent.workflow_library import WorkflowLibrary

            library = WorkflowLibrary()
            self._workflow_library_instance = library
        return library

    def save_workflow(self, task_id: str, name: str) -> dict[str, Any]:
        """Save a completed task summary after rechecking the normal access gates."""
        self._ensure_can_continue()
        task = self.store.load(str(task_id or ""))
        if task is None:
            raise ValueError("The requested task was not found.")
        return self._workflow_library().save(task, name)

    def list_workflows(self) -> list[dict[str, Any]]:
        self._ensure_can_continue()
        return self._workflow_library().list()

    def suggest_workflows(self, objective: str) -> list[dict[str, Any]]:
        self._ensure_can_continue()
        return self._workflow_library().suggest(objective)

    def run_saved_workflow(self, workflow_id: str) -> Task:
        """Re-plan a saved template; never replay stored commands or actions."""
        self._ensure_can_continue()
        request = self._workflow_library().build_fresh_request(workflow_id)
        return self.start(
            request["objective"],
            criteria=request["criteria"],
            source="saved_workflow",
        )

    # ── tool entry point ---------------------------------------------------
    def handle_tool(self, params: dict[str, Any], speak: Callable[[str], None] | None = None) -> str:
        """Action-handler facade. Always returns a sentence the model can say."""
        if speak is not None:
            self.attach_speaker(speak)
        action = str((params or {}).get("action") or "status").strip().lower()
        objective = str((params or {}).get("objective") or "").strip()
        criteria = params.get("criteria") if isinstance(params, dict) else None
        criteria_list = [str(item) for item in (criteria or []) if str(item).strip()]

        try:
            if action in {"run", "start", "begin"}:
                if not objective:
                    return "Tell me the objective to work on."
                task = self.start(objective, criteria=criteria_list)
                plan_hint = (
                    "" if task.steps else " I'll plan it in the background."
                )
                return (f"Starting an autonomous task: {objective[:160]}.{plan_hint} "
                        "I'll keep working and only speak up at real milestones.")
            if action in {"stop", "cancel", "halt"}:
                return ("Stopping the current task." if self.stop()
                        else "No autonomous task is running.")
            if action == "pause":
                return "Paused." if self.pause() else "Nothing is running to pause."
            if action == "resume":
                if self.resume():
                    return "Continuing the task."
                resumed = self.resume_last()
                return ("Resumed the last unfinished task." if resumed
                        else "There is no paused or unfinished task.")
            if action == "save_workflow":
                task_id = str(params.get("task_id") or "").strip()
                name = str(params.get("name") or "").strip()
                saved = self.save_workflow(task_id, name)
                return f"Saved workflow '{saved['name']}'. It will be freshly planned whenever reused."
            if action == "list_workflows":
                workflows = self.list_workflows()
                if not workflows:
                    return "There are no saved workflows yet."
                return "Saved workflows: " + "; ".join(
                    f"{item['name']} ({item['step_count']} steps)" for item in workflows[:8]
                )
            if action == "suggest_workflows":
                suggestions = self.suggest_workflows(objective)
                if not suggestions:
                    return "No matching saved workflows were found."
                return "Possible workflow templates: " + "; ".join(
                    item["name"] for item in suggestions
                )
            if action == "run_workflow":
                workflow_id = str(params.get("workflow_id") or "").strip()
                task = self.run_saved_workflow(workflow_id)
                return f"Re-planning saved workflow as a new task: {task.objective[:140]}."
            if action in {"report", "result"}:
                report = self.report_text()
                return report or "The task has not produced a report yet."
            if action in {"pending", "list"}:
                unfinished = self.store.unfinished()
                if not unfinished:
                    return "No unfinished tasks."
                return "Unfinished tasks: " + "; ".join(
                    f"{task.objective[:60]} ({task.state.value}, "
                    f"{int(task.progress() * 100)}%)" for task in unfinished[:4]
                )
            return self.status_sentence()
        except PermissionError as exc:
            return str(exc)
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            self._log(f"Agent tool error: {redact(exc, 300)}")
            return f"The agent could not complete that request: {redact(exc, 200)}"

    # ── settings -----------------------------------------------------------
    def set_screen_paused(self, paused: bool) -> None:
        self._manual_screen_paused = bool(paused)
        privacy_locked = self._privacy_locked()
        self.capture.set_paused(self._manual_screen_paused or privacy_locked)
        state = "paused" if self._manual_screen_paused or privacy_locked else "resumed"
        self._log(f"Agent screen access {state} by the owner.")

    def set_voice_updates(self, enabled: bool) -> None:
        self._announcer.enabled = bool(enabled)

    # ── authorization hooks ------------------------------------------------
    def _privacy_locked(self) -> bool:
        try:
            from jarvis.security.auth_manager import PRIVACY_LOCK
            from jarvis.core.security import get_auth_state

            return get_auth_state() == PRIVACY_LOCK
        except Exception:
            # Missing or broken security state must never be interpreted as unlocked.
            return True

    def _sync_capture_access(self) -> bool:
        """Apply Privacy Lock to screen capture even if it changes mid-task."""
        locked = self._privacy_locked()
        self.capture.set_paused(self._manual_screen_paused or locked)
        return locked

    def _ensure_can_continue(self) -> None:
        """Recheck the existing owner and privacy gates before task continuation."""
        if not self.settings.enabled:
            raise PermissionError("Autonomous tasks are switched off in settings.")
        if self._sync_capture_access():
            raise PermissionError("Privacy Lock is active. Autonomous work is blocked.")
        if not self._owner_authorized():
            raise PermissionError("Owner verification is required to continue autonomous work.")

    def _authorize_task_step(self, step: TaskStep) -> str | None:
        """Revalidate session state before each step and every retry."""
        if not self.settings.enabled:
            return "Autonomous tasks are switched off in settings."
        if self._sync_capture_access():
            return "Privacy Lock is active. Autonomous work is paused."
        if not self._owner_authorized():
            return "Owner verification expired; autonomous work is blocked."
        return None

    def _owner_authorized(self) -> bool:
        try:
            from jarvis.core.security import is_owner_access_allowed

            return bool(is_owner_access_allowed())
        except Exception:
            return False

    def _authorize_desktop(self, description: str) -> tuple[bool, str]:
        """Desktop actions inherit the task scope and recheck live owner access."""
        if self._sync_capture_access():
            return False, "Privacy Lock is active."
        if not self._owner_authorized():
            return False, "Owner verification is required for desktop control."
        if not self.settings.allow_desktop:
            return False, "Desktop control is disabled in autonomy settings."
        if self.settings.dry_run:
            return True, "dry-run"
        return True, "within the authorized task"

    def _request_approval(self, step: TaskStep, decision: Any) -> bool:
        """Consequential step: ask the owner through the existing confirm gate."""
        if self._sync_capture_access() or not self._owner_authorized():
            self._log(f"Agent approval denied (owner not verified or Privacy Lock active): {step.title}")
            return False
        try:
            from jarvis.core import confirm
        except Exception:
            return False
        is_bound = getattr(confirm, "is_bound", None)
        if callable(is_bound) and not is_bound():
            # Headless: nobody is present to approve. Deny, never assume consent.
            self._log("Agent approval denied: no confirmation UI is connected.")
            return False
        approved = threading.Event()

        def _run() -> str:
            approved.set()
            return "approved"

        try:
            message = confirm.request(
                key=f"agent-{step.id}",
                title="Authorize a consequential action",
                detail=(f"Task: {step.title}\nStep kind: {step.kind.value}\n"
                        f"Reason: {getattr(decision, 'reason', '')}\n"
                        f"Command/target: {(step.command or step.target or step.path)[:300]}"),
                run=_run,
            )
        except Exception as exc:
            self._log(f"Agent approval request failed: {redact(exc, 200)}")
            return False
        if not str(message).startswith("[CONFIRMATION_PENDING]"):
            self._log(f"Agent approval not granted: {str(message)[:160]}")
            return False
        return approved.wait(timeout=self.engine.policy.approval_timeout_s)

    # ── planning model -----------------------------------------------------
    def _model_asker(self) -> Callable[[str], str] | None:
        """A text-in/text-out callable, or None when no provider is configured."""
        try:
            from jarvis.memory.config_manager import load_api_keys

            config = load_api_keys() or {}
        except Exception:
            config = {}
        import os

        has_key = any(
            (os.environ.get(env) or "").strip() or str(config.get(key) or "").strip()
            for env, key in (
                ("GEMINI_API_KEY", "gemini_api_key"),
                ("OPENAI_API_KEY", "openai_api_key"),
                ("ANTHROPIC_API_KEY", "anthropic_api_key"),
                ("GROQ_API_KEY", "groq_api_key"),
            )
        )
        if not has_key:
            return None

        def ask(prompt: str) -> str:
            from jarvis.core.hybrid_llm_router import HybridLLMRouter, resolve_preferred_provider

            router = HybridLLMRouter(
                resolve_preferred_provider(config),
                api_keys=config,
                timeout=60.0,
                online_check=False,
            )
            result = router.query(
                prompt,
                system_prompt=(
                    "You are JARVIS's task planner. Answer with JSON only, as "
                    "instructed by the user's message."
                ),
            )
            return str(result.get("text") or "")

        return ask

    # ── internal -----------------------------------------------------------
    def _on_event(self, event: AgentEvent) -> None:
        try:
            task = self.runner.active_task
            if task is not None:
                with self._lock:
                    self._last_task_snapshot = task
                    self._last_task_id = task.id
            self._announcer.announce(event)
            if event.kind == "finished":
                from jarvis.core import hooks
                hooks.emit("task_finished", {"task_id": event.task_id, "state": event.state.value,
                                             "message": str(event.message)[:300]})
        except Exception:
            failsoft.suppress("agent.integration:_on_event")

    def _cached_latest_task(self) -> Task | None:
        with self._lock:
            return self._last_task_snapshot

    def _schedule_history_refresh(self) -> None:
        """Refresh the initial cloud history snapshot away from the Qt polling path."""
        with self._history_refresh_lock:
            if self._history_refresh_started or self._cached_latest_task() is not None:
                return
            self._history_refresh_started = True
        threading.Thread(
            target=self._refresh_latest_task_snapshot,
            daemon=True,
            name="JarvisAgentHistoryRefresh",
        ).start()

    def _refresh_latest_task_snapshot(self) -> None:
        try:
            entries = self.store.list_tasks(limit=1)
            task_id = str(entries[0].get("id") or "") if entries else ""
            task = self.store.load(task_id) if task_id else None
            if task is not None:
                with self._lock:
                    self._last_task_id = task.id
                    self._last_task_snapshot = task
        except Exception as exc:
            logger.warning("Initial cloud task history refresh failed (%s)", type(exc).__name__)

    def _on_milestone(self, message: str) -> None:
        # The announcer already handles rate limiting; this exists for callers
        # that need a single sentence without constructing an event.
        if self._speak is None or not message:
            return
        if message.endswith(("complete.", "Task complete.")):
            self._announcer.say(message)

    def _latest_task(self) -> Task | None:
        cached = self._cached_latest_task()
        if cached is not None:
            return cached
        with self._lock:
            task_id = getattr(self, "_last_task_id", "")
        if not task_id:
            entries = self.store.list_tasks(limit=1)
            task_id = str(entries[0].get("id") or "") if entries else ""
        if not task_id:
            return None
        task = self.store.load(task_id)
        if task is not None:
            with self._lock:
                self._last_task_snapshot = task
        return task


def get_service() -> AgentService:
    """Return the process-wide service, creating it on first use."""
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = AgentService()
        return _SERVICE


def reset_service(service: AgentService | None = None) -> None:
    """Replace (or clear) the singleton. Tests use this; the app does not."""
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is not None and _SERVICE is not service:
            try:
                _SERVICE.shutdown()
            except Exception:
                failsoft.suppress("agent.integration:reset_service")
        _SERVICE = service


def shutdown_service() -> None:
    """Stop a running task and release capture handles at application exit."""
    global _SERVICE
    with _SERVICE_LOCK:
        service = _SERVICE
    if service is not None:
        try:
            service.shutdown()
        except Exception:
            failsoft.suppress("agent.integration:shutdown_service")


def service_available() -> bool:
    try:
        return get_service() is not None
    except Exception:
        return False


def is_task_active() -> bool:
    try:
        service = get_service()
    except Exception:
        return False
    task = service.runner.active_task
    return bool(task and not task.state.terminal)


__all__ = [
    "AgentService",
    "Task",
    "TaskState",
    "get_service",
    "is_task_active",
    "reset_service",
    "shutdown_service",
    "service_available",
]
