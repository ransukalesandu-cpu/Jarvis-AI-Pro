"""Headless tests for the extracted application lifecycle boundary."""

from __future__ import annotations

from types import SimpleNamespace

from core.runtime.application import run_desktop, run_headless


class Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class FakeApplication:
    current = None

    def __init__(self, argv):
        self.argv = argv
        self.style = None
        self.aboutToQuit = Signal()
        self.executed = False
        FakeApplication.current = self

    @classmethod
    def instance(cls):
        return cls.current

    def setStyle(self, style):
        self.style = style

    def exec(self):
        self.executed = True


class FakeTimer:
    @staticmethod
    def singleShot(_delay, callback):
        callback()


class FakeThread:
    def __init__(self, *, target, daemon):
        assert daemon is False
        self.target = target

    def start(self):
        self.target()


class FakeSplash:
    def __init__(self):
        self.finished = Signal()
        self.closed = False
        self.started = False

    def start(self):
        self.started = True
        self.finished.callback()

    def close(self):
        self.closed = True


def test_headless_runtime_keeps_existing_live_runner():
    calls = []
    live = SimpleNamespace(run=lambda: "live-coroutine")

    run_headless(
        ui_factory=lambda: "headless-ui",
        live_factory=lambda ui: (calls.append(("live", ui)) or live),
        asyncio_runner=lambda coroutine: calls.append(("run", coroutine)),
        print_fn=lambda *_args: None,
    )

    assert calls == [("live", "headless-ui"), ("run", "live-coroutine")]


def test_desktop_runtime_starts_splash_then_ui_and_live():
    FakeApplication.current = None
    calls = []
    splash = FakeSplash()

    class FakeUI:
        def __init__(self, face):
            calls.append(("ui", face))

        def wait_for_api_key(self, stop_event):
            calls.append(("api-key", stop_event.is_set()))
            return True

        def write_log(self, message):
            calls.append(("log", message))

        def set_state(self, state):
            calls.append(("state", state))

        def request_close(self):
            calls.append(("close-ui",))

    class FakeLive:
        def __init__(self, ui):
            calls.append(("live", ui))
            self._shutdown_requested = False

        def run(self):
            return "live-coroutine"

        def request_shutdown(self):
            calls.append(("shutdown-live",))

    run_desktop(
        argv=["jarvis"],
        ui_class=FakeUI,
        live_class=FakeLive,
        qt_application_class=FakeApplication,
        qt_timer_class=FakeTimer,
        splash_class_loader=lambda: (lambda: splash),
        agent_shutdown_loader=lambda: (lambda: calls.append(("shutdown-agent",))),
        thread_factory=FakeThread,
        asyncio_runner=lambda coroutine: calls.append(("run", coroutine)),
        configure_graphics_backend=lambda: calls.append(("graphics",)),
        print_fn=lambda *_args: None,
    )

    app = FakeApplication.current
    assert app.argv == ["jarvis"]
    assert app.style == "Fusion"
    assert app.executed
    assert splash.started and splash.closed
    assert calls[0] == ("graphics",)
    assert calls[1] == ("ui", "face.png")
    assert calls[2][0] == "api-key"
    assert calls[3][0] == "live"
    assert calls[4] == ("run", "live-coroutine")

    app.aboutToQuit.callback()
    assert calls[-1] == ("shutdown-agent",)


def test_desktop_runtime_falls_back_when_splash_cannot_load():
    FakeApplication.current = None
    calls = []

    class FakeUI:
        def __init__(self, face):
            calls.append(("ui", face))

        def wait_for_api_key(self, _stop_event):
            return False

    run_desktop(
        argv=["jarvis"],
        ui_class=FakeUI,
        live_class=object,
        qt_application_class=FakeApplication,
        qt_timer_class=FakeTimer,
        splash_class_loader=lambda: (_ for _ in ()).throw(ImportError("no splash")),
        agent_shutdown_loader=lambda: (lambda: None),
        thread_factory=FakeThread,
        print_fn=lambda *_args: None,
    )

    assert calls == [("ui", "face.png")]
    assert FakeApplication.current.executed
