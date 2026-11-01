"""Desktop and headless application lifecycle orchestration.

This module deliberately receives JARVIS feature classes from the legacy
entrypoint instead of importing them. That keeps the runtime boundary small,
avoids circular imports, and preserves the existing Live/audio/security
implementation while startup responsibilities move out of main.py.
"""
from __future__ import annotations

import asyncio
import threading
import traceback
from collections.abc import Callable, Sequence
from typing import Any


def run_headless(
    *,
    ui_factory: Callable[[], Any],
    live_factory: Callable[[Any], Any],
    asyncio_runner: Callable[[Any], Any] = asyncio.run,
    traceback_printer: Callable[[], Any] = traceback.print_exc,
    print_fn: Callable[..., Any] = print,
) -> None:
    """Run the existing Live assistant without creating a desktop UI."""
    print_fn("[JARVIS Core] Starting in Headless Daemon Mode...")
    ui = ui_factory()
    jarvis = live_factory(ui)
    try:
        asyncio_runner(jarvis.run())
    except KeyboardInterrupt:
        print_fn("\n[JARVIS Core] Headless core shutting down...")
    except Exception as exc:
        print_fn(
            f"[JARVIS Core] Headless runtime failed: "
            f"{type(exc).__name__}: {exc}"
        )
        traceback_printer()


def _load_qt_application_types() -> tuple[Any, Any]:
    """Import Qt only when the desktop runtime is actually requested."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    return QApplication, QTimer


def _load_startup_splash() -> Any:
    from core.startup_sequence import StartupSequenceSplash

    return StartupSequenceSplash


def _load_agent_shutdown() -> Callable[[], Any]:
    from agent.integration import shutdown_service

    return shutdown_service


def run_desktop(
    *,
    argv: Sequence[str],
    ui_class: type,
    live_class: type,
    configure_graphics_backend: Callable[[], Any] | None = None,
    qt_application_class: Any | None = None,
    qt_timer_class: Any | None = None,
    splash_class_loader: Callable[[], type] = _load_startup_splash,
    agent_shutdown_loader: Callable[[], Callable[[], Any]] = _load_agent_shutdown,
    thread_factory: Callable[..., Any] = threading.Thread,
    asyncio_runner: Callable[[Any], Any] = asyncio.run,
    traceback_printer: Callable[[], Any] = traceback.print_exc,
    failsoft_suppress: Callable[[str], Any] | None = None,
    print_fn: Callable[..., Any] = print,
) -> None:
    """Create the Qt application and coordinate splash, UI, Live, and shutdown.

    Qt and the splash are loaded lazily. The UI, Live session, authentication,
    ActionDispatcher, and privacy gates are supplied by the existing entrypoint
    and are not recreated or bypassed here.
    """
    if qt_application_class is None or qt_timer_class is None:
        loaded_application, loaded_timer = _load_qt_application_types()
        qt_application_class = qt_application_class or loaded_application
        qt_timer_class = qt_timer_class or loaded_timer

    if configure_graphics_backend is not None:
        configure_graphics_backend()

    app = qt_application_class.instance() or qt_application_class(list(argv))
    app.setStyle("Fusion")
    startup: dict[str, Any] = {
        "ui": None,
        "splash": None,
        "jarvis": None,
        "stop_event": threading.Event(),
    }

    def stop_live_on_app_exit() -> None:
        startup["stop_event"].set()
        live = startup.get("jarvis")
        if live is not None:
            live.request_shutdown()
        try:
            agent_shutdown_loader()()
        except Exception:
            if failsoft_suppress is not None:
                failsoft_suppress("main:main")

    app.aboutToQuit.connect(stop_live_on_app_exit)

    def launch_jarvis() -> None:
        if startup["ui"] is not None:
            return
        splash = startup["splash"]
        if splash is not None:
            splash.close()

        print_fn("[JARVIS] Launching the original JARVIS desktop UI.")
        ui = ui_class("face.png")
        startup["ui"] = ui

        def runner() -> None:
            if not ui.wait_for_api_key(startup["stop_event"]):
                return
            jarvis = live_class(ui)
            startup["jarvis"] = jarvis
            try:
                asyncio_runner(jarvis.run())
            except KeyboardInterrupt:
                print_fn("\n🔴 Shutting down...")
            except Exception as exc:
                print_fn(
                    "[CRITICAL THREAD CRASH] JARVIS runtime worker stopped: "
                    f"{type(exc).__name__}: {exc}"
                )
                traceback_printer()
                try:
                    ui.write_log(
                        "ERR: JARVIS runtime stopped unexpectedly: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    ui.set_state("ERROR")
                except Exception:
                    if failsoft_suppress is not None:
                        failsoft_suppress(
                            "main:main.launch_jarvis.runner"
                        )
            finally:
                if jarvis._shutdown_requested:
                    ui.request_close()

        thread_factory(target=runner, daemon=False).start()

    try:
        splash_class = splash_class_loader()
        splash = splash_class()
        startup["splash"] = splash
        splash.finished.connect(launch_jarvis)
        splash.start()
    except Exception as exc:
        print_fn(
            "[Startup] Cinematic boot screen unavailable; "
            f"opening JARVIS directly: {exc}"
        )
        startup["splash"] = None
        qt_timer_class.singleShot(0, launch_jarvis)

    app.exec()
