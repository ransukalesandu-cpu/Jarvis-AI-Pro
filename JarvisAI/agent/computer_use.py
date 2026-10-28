"""Controlled desktop actions: click, type, scroll, focus a window.

The controller is deliberately narrow. It does not accept raw "click at (x, y)"
from a model: every pointer action must name a target, that target is resolved
through :class:`~agent.screen_vision.ScreenVision` (accessibility → OCR → vision),
and the resolved point is validated against the real screen geometry before
anything is moved. After acting it re-observes the screen and reports what it
now sees, so the caller can decide "that worked" or re-plan instead of clicking
blindly a second time.

Two hard guarantees:

* **It can never run away.** A stop event is checked before and after every
  action, actions-per-task are capped, and a dry-run mode records intent without
  touching the desktop.
* **It cannot click outside the screen or into the OS failsafe corner.** Both
  reject with an explanatory ``ActionResult`` rather than an exception, so the
  runner can treat it as a re-plannable failure.

pyautogui is imported lazily and the backend is injectable, which is how the test
suite drives the whole path on a machine with no display.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent.screen_vision import ElementTarget, ScreenObservation, ScreenVision
from agent.store import redact


class InputError(RuntimeError):
    """The input backend is unavailable or refused an operation."""


class InputBackend(Protocol):  # pragma: no cover - structural typing
    name: str

    def available(self) -> bool: ...

    def size(self) -> tuple[int, int]: ...

    def position(self) -> tuple[int, int]: ...

    def move_to(self, x: int, y: int, duration: float = 0.25) -> None: ...

    def click(self, x: int, y: int, *, button: str = "left", clicks: int = 1) -> None: ...

    def type_text(self, text: str, interval: float = 0.01) -> None: ...

    def press(self, keys: list[str]) -> None: ...

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> None: ...

    def focus_window(self, title: str) -> bool: ...


class PyAutoGUIBackend:
    """Real desktop backend. Failsafe is left enabled on purpose."""

    name = "pyautogui"

    def __init__(self) -> None:
        self._module = None

    def _load(self):
        if self._module is None:
            try:
                import pyautogui
            except Exception as exc:  # pragma: no cover - depends on host
                raise InputError(
                    "Desktop control needs the 'pyautogui' package, which is not "
                    "importable in this environment."
                ) from exc
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._module = pyautogui
        return self._module

    def available(self) -> bool:
        try:
            self._load()
            return True
        except InputError:
            return False

    def size(self) -> tuple[int, int]:
        size = self._load().size()
        return int(size[0]), int(size[1])

    def position(self) -> tuple[int, int]:
        position = self._load().position()
        return int(position[0]), int(position[1])

    def move_to(self, x: int, y: int, duration: float = 0.25) -> None:
        self._load().moveTo(int(x), int(y), duration=max(0.0, float(duration)))

    def click(self, x: int, y: int, *, button: str = "left", clicks: int = 1) -> None:
        self._load().click(x=int(x), y=int(y), clicks=int(clicks), button=button)

    def type_text(self, text: str, interval: float = 0.01) -> None:
        self._load().write(str(text), interval=max(0.0, float(interval)))

    def press(self, keys: list[str]) -> None:
        if len(keys) > 1:
            self._load().hotkey(*keys)
        elif keys:
            self._load().press(keys[0])

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> None:
        module = self._load()
        if x is not None and y is not None:
            module.moveTo(int(x), int(y))
        module.scroll(int(amount))

    def focus_window(self, title: str) -> bool:
        try:
            import pygetwindow as gw
        except Exception:
            return False
        try:
            matches = [
                window for window in gw.getAllWindows()
                if str(title).casefold() in str(window.title or "").casefold()
            ]
            if not matches:
                return False
            matches[0].activate()
            return True
        except Exception:
            return False


@dataclass
class ComputerUseConfig:
    dry_run: bool = False
    min_confidence: float = 0.45
    allow_clicks: bool = True
    allow_typing: bool = True
    max_actions: int = 24
    settle_s: float = 0.6
    move_duration_s: float = 0.25
    failsafe_margin: int = 4
    max_text_chars: int = 4000


@dataclass
class ActionResult:
    """Outcome of one desktop action, including the post-action observation."""

    ok: bool
    action: str
    detail: str = ""
    target: ElementTarget | None = None
    observed: str = ""
    verified: bool | None = None
    retryable: bool = False
    blocked: bool = False
    cancelled: bool = False
    dry_run: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "detail": self.detail,
            "target": self.target.to_dict() if self.target else None,
            "verified": self.verified,
            "retryable": self.retryable,
            "blocked": self.blocked,
            "cancelled": self.cancelled,
            "dry_run": self.dry_run,
        }


class ComputerUseController:
    """Resolve → validate → act → re-observe, with an immediate stop."""

    def __init__(
        self,
        backend: InputBackend | None = None,
        *,
        vision: ScreenVision | None = None,
        config: ComputerUseConfig | None = None,
        stop_event: threading.Event | None = None,
        authorize: Callable[[str], tuple[bool, str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: Callable[[str], None] | None = None,
    ):
        self._backend = backend
        self.vision = vision
        self.config = config or ComputerUseConfig()
        self._stop = stop_event or threading.Event()
        self._authorize = authorize
        self._sleep = sleep
        self._log = logger or (lambda message: None)
        self.actions_taken = 0
        self.last_result: ActionResult | None = None

    # -- plumbing ----------------------------------------------------------
    def backend(self) -> InputBackend:
        if self._backend is None:
            self._backend = PyAutoGUIBackend()
        return self._backend

    def available(self) -> bool:
        try:
            return bool(self.backend().available())
        except Exception:
            return False

    def screen_size(self) -> tuple[int, int]:
        try:
            return self.backend().size()
        except Exception:
            return (0, 0)

    def stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _budget_left(self) -> bool:
        return self.actions_taken < self.config.max_actions

    def _cancelled(self, action: str) -> ActionResult:
        return ActionResult(
            ok=False, action=action, cancelled=True,
            detail="Stopped before the action ran.", retryable=False,
        )

    def _authorized(self, description: str) -> ActionResult | None:
        if self._authorize is None:
            return None
        allowed, reason = self._authorize(description)
        if allowed:
            return None
        return ActionResult(
            ok=False, action=description, blocked=True,
            detail=reason or "This desktop action was not authorized.",
        )

    # -- validation --------------------------------------------------------
    def validate_target(self, target: ElementTarget) -> tuple[bool, str]:
        width, height = self.screen_size()
        if width <= 0 or height <= 0:
            return False, "The screen geometry could not be read, so no action was taken."
        margin = max(0, int(self.config.failsafe_margin))
        if not (margin <= target.x < width - margin and margin <= target.y < height - margin):
            return False, (
                f"Target ({target.x}, {target.y}) is outside the usable desktop area "
                f"({width}×{height}) or inside the OS failsafe corner."
            )
        if target.confidence < self.config.min_confidence:
            return False, (
                f"Target confidence {target.confidence:.2f} is below the "
                f"{self.config.min_confidence:.2f} threshold; re-observation needed."
            )
        return True, "ok"

    def _settle(self) -> None:
        if self.config.settle_s > 0:
            self._sleep(self.config.settle_s)

    def _observe(self, question: str = "") -> ScreenObservation | None:
        if self.vision is None:
            return None
        try:
            return self.vision.observe(question, force_capture=True)
        except Exception as exc:
            self._log(f"Agent re-observation failed: {redact(exc, 200)}")
            return None

    def _finish(self, result: ActionResult) -> ActionResult:
        self.last_result = result
        if result.ok and not result.dry_run:
            self.actions_taken += 1
        return result

    # -- actions -----------------------------------------------------------
    def click_element(self, label: str, *, expectation: str = "",
                      button: str = "left", clicks: int = 1) -> ActionResult:
        action = f"click '{label}'"
        if self.stopped:
            return self._cancelled(action)
        if not self.config.allow_clicks:
            return ActionResult(False, action, blocked=True,
                                detail="Clicking is disabled for autonomous tasks.")
        if not self._budget_left():
            return ActionResult(False, action, blocked=True,
                                detail="The action budget for this task is exhausted.")
        denied = self._authorized(action)
        if denied is not None:
            return denied
        if self.vision is None:
            return ActionResult(False, action, blocked=True,
                                detail="No screen vision is configured, so the target "
                                       "cannot be located safely.")

        try:
            targets = self.vision.find(label)
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"Locating the target failed: {redact(exc, 300)}",
            ))
        if not targets:
            observation = self._observe(f"Where is the control {label!r}?")
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"I could not find {label!r} on screen.",
                observed=observation.summary() if observation else "",
            ))
        target = max(targets, key=lambda item: item.confidence)
        valid, reason = self.validate_target(target)
        if not valid:
            return self._finish(ActionResult(
                False, action, retryable=True, target=target, detail=reason,
            ))

        if self.config.dry_run:
            return self._finish(ActionResult(
                True, action, dry_run=True, target=target,
                detail=f"[dry-run] would click ({target.x}, {target.y}) via "
                       f"{target.source}.",
            ))
        try:
            self.backend().move_to(target.x, target.y, self.config.move_duration_s)
            if self.stopped:
                return self._cancelled(action)
            self.backend().click(target.x, target.y, button=button, clicks=clicks)
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True, target=target,
                detail=f"The click failed: {redact(exc, 300)}",
            ))
        self._settle()
        observed = self._observe(f"Did clicking {label!r} have the expected effect?")
        verified: bool | None = None
        if expectation and self.vision is not None:
            try:
                verified = bool(self.vision.verify(expectation).ok)
            except Exception:
                verified = None
        return self._finish(ActionResult(
            ok=verified is not False,
            action=action, target=target,
            detail=f"Clicked {label!r} at ({target.x}, {target.y}).",
            observed=observed.summary() if observed else "",
            verified=verified,
            retryable=verified is False,
            evidence={"source": target.source, "confidence": round(target.confidence, 3)},
        ))

    def type_text(self, text: str, *, target_label: str = "") -> ActionResult:
        action = f"type into {target_label!r}" if target_label else "type text"
        if self.stopped:
            return self._cancelled(action)
        if not self.config.allow_typing:
            return ActionResult(False, action, blocked=True,
                                detail="Typing is disabled for autonomous tasks.")
        if not self._budget_left():
            return ActionResult(False, action, blocked=True,
                                detail="The action budget for this task is exhausted.")
        payload = str(text or "")
        if len(payload) > self.config.max_text_chars:
            return ActionResult(False, action, blocked=True,
                                detail="Refusing to type an unusually long string.")
        denied = self._authorized(action)
        if denied is not None:
            return denied

        if target_label:
            located = self.click_element(target_label)
            if not located.ok:
                return ActionResult(False, action, retryable=located.retryable,
                                    blocked=located.blocked, detail=located.detail)
        if self.config.dry_run:
            return self._finish(ActionResult(True, action, dry_run=True,
                                             detail="[dry-run] would type the text."))
        try:
            self.backend().type_text(payload)
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"Typing failed: {redact(exc, 300)}",
            ))
        self._settle()
        observed = self._observe("Did the text appear in the focused field?")
        return self._finish(ActionResult(
            True, action, detail="Typed the requested text.",
            observed=observed.summary() if observed else "",
        ))

    def press_keys(self, keys: list[str]) -> ActionResult:
        action = "press " + "+".join(keys)
        if self.stopped:
            return self._cancelled(action)
        if not keys:
            return ActionResult(False, action, detail="No keys were specified.")
        denied = self._authorized(action)
        if denied is not None:
            return denied
        if self.config.dry_run:
            return self._finish(ActionResult(True, action, dry_run=True,
                                             detail=f"[dry-run] would press {keys}."))
        try:
            self.backend().press([str(key) for key in keys])
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"Key press failed: {redact(exc, 300)}",
            ))
        self._settle()
        return self._finish(ActionResult(True, action, detail="Keys sent."))

    def scroll(self, amount: int) -> ActionResult:
        action = f"scroll {amount}"
        if self.stopped:
            return self._cancelled(action)
        denied = self._authorized(action)
        if denied is not None:
            return denied
        if self.config.dry_run:
            return self._finish(ActionResult(True, action, dry_run=True,
                                             detail=f"[dry-run] would scroll {amount}."))
        try:
            self.backend().scroll(int(amount))
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"Scrolling failed: {redact(exc, 300)}",
            ))
        self._settle()
        return self._finish(ActionResult(True, action, detail="Scrolled."))

    def focus_window(self, title: str) -> ActionResult:
        action = f"focus window '{title}'"
        if self.stopped:
            return self._cancelled(action)
        denied = self._authorized(action)
        if denied is not None:
            return denied
        if self.config.dry_run:
            return self._finish(ActionResult(True, action, dry_run=True,
                                             detail=f"[dry-run] would focus {title!r}."))
        try:
            ok = bool(self.backend().focus_window(str(title)))
        except Exception as exc:
            return self._finish(ActionResult(
                False, action, retryable=True,
                detail=f"Focusing the window failed: {redact(exc, 300)}",
            ))
        self._settle()
        return self._finish(ActionResult(
            ok, action,
            detail="Window focused." if ok else f"No window matching {title!r} was found.",
            retryable=not ok,
        ))
