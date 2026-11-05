"""Preview the new UI on its own: ``python -m jarvis.webui``.

Shows real telemetry only. It is not wired to the assistant yet, so it never invents a state.
"""
from __future__ import annotations

import sys


def main() -> int:
    from . import dist_ready

    if not dist_ready():
        print("jarvis/webui/dist is missing. Build it with: cd frontend && npm install && npm run build", file=sys.stderr)
        return 2
    from PyQt6.QtCore import QCoreApplication, Qt

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must be imported before QApplication)
    from PyQt6.QtWidgets import QApplication

    from .host import WebUIHost

    app = QApplication(sys.argv)
    w = WebUIHost()
    w.setWindowTitle("JARVIS")
    w.resize(1280, 800)
    w.show()
    code = app.exec()
    w.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
