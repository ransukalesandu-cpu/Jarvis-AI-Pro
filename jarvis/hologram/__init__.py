"""Neural Entity Engine 2.0: WebGL hologram rendered in a locked-down QWebEngineView.

Importing this package is cheap. The Qt WebEngine host lives in ``jarvis.hologram.host`` and
must be imported lazily by UI code.
"""


def prepare_qt() -> None:
    """Call before the QApplication is created.

    QtWebEngine requires either its widgets module to be imported, or this attribute to be set,
    before the application object exists. Setting the attribute is cheap (QtCore only), so the
    WebEngine itself is still loaded lazily when the HUD builds.
    """
    try:
        from PyQt6.QtCore import QCoreApplication, Qt
        if QCoreApplication.instance() is None:
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    except Exception:  # never block startup over a rendering preference
        return
