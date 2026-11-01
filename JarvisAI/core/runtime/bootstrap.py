"""Application bootstrap for the JARVIS desktop and headless runtimes.

This module owns process startup and shutdown orchestration. Feature-specific
services remain in their existing modules; imports of Qt and optional services
are deliberately deferred until the desktop path is selected.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any


def run_application(
    *,
    headless_ui_factory: Callable[[], Any],
    live_factory: Callable[[Any], Any],
    desktop_ui_factory: Callable[[str], Any] | None,
    configure_graphics_backend: Callable[[], Any] | None = None,
    suppress_error: Callable[[str], Any] | None = None,
    argv: list[str] | None = None,
) -> int | None:
    """Start JARVIS in headless or desktop mode using injected app services."""
    parser = argparse.ArgumentParser(description="JARVIS AI Personal Assistant")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless background daemon mode",
    )
    args, _ = parser.parse_known_args(argv)

    if args.headless:
        print("[JARVIS Core] Starting in Headless Daemon Mode...")
        ui = headless_ui_factory()
        jarvis = live_factory(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\\n[JARVIS Core] Headless core shutting down...")
        except Exception as exc:
            print(
                f"[JARVIS Core] Headless runtime failed: "
                f"{type(exc).__name__}: {exc}"
            )
            traceback.print_exc()
        return None

    if desktop_ui_factory is None:
        print(
            "[JARVIS] The original desktop UI could not be loaded. "
            "Install or repair the desktop UI dependencies."
        )
        return None

    # Qt is intentionally imported only for the desktop launch path.
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    if configure_graphics_backend:
        configure_graphics_backend()
    app = QApplication.instance() or QApplication(sys.argv)
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
            from agent.integration import shutdown_service

            shutdown_service()
        except Exception:
            if suppress_error is not None:
                suppress_error("runtime:stop_live_on_app_exit")

    app.aboutToQuit.connect(stop_live_on_app_exit)

    def launch_jarvis() -> None:
        if startup["ui"] is not None:
            return
        splash = startup["splash"]
        if splash is not None:
            splash.close()

        print("[JARVIS] Launching the original JARVIS desktop UI.")
        ui = desktop_ui_factory("face.png")
        startup["ui"] = ui

        def runner() -> None:
            if not ui.wait_for_api_key(startup["stop_event"]):
                return
            jarvis = live_factory(ui)
            startup["jarvis"] = jarvis
            try:
                asyncio.run(jarvis.run())
            except KeyboardInterrupt:
                print("\\n🔴 Shutting down...")
            except Exception as exc:
                print(
                    f"[CRITICAL THREAD CRASH] JARVIS runtime worker stopped: "
                    f"{type(exc).__name__}: {exc}"
                )
                traceback.print_exc()
                try:
                    ui.write_log(
                        "ERR: JARVIS runtime stopped unexpectedly: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    ui.set_state("ERROR")
                except Exception:
                    if suppress_error is not None:
                        suppress_error("runtime:launch_jarvis.runner")
            finally:
                if jarvis._shutdown_requested:
                    ui.request_close()

        threading.Thread(target=runner, daemon=False).start()

    try:
        from core.startup_sequence import StartupSequenceSplash

        splash = StartupSequenceSplash()
        startup["splash"] = splash
        splash.finished.connect(launch_jarvis)
        splash.start()
    except Exception as exc:
        print(
            "[Startup] Cinematic boot screen unavailable; "
            f"opening JARVIS directly: {exc}"
        )
        startup["splash"] = None
        QTimer.singleShot(0, launch_jarvis)

    return app.exec()
