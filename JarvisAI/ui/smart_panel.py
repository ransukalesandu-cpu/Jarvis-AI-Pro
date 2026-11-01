
"""Lightweight HTML/CSS smart navigation chrome for the side workspace.

The panel is rendered by Qt's QTextBrowser rather than Chromium/WebEngine. Links
use a private jarvis:// URL scheme and are routed through a strict allowlist
to the Python UI, so the HTML layer never receives direct backend access.
"""
from __future__ import annotations

import html
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import QFrame, QTextBrowser


class SmartPanelHeader(QTextBrowser):
    """Compact HTML/CSS header with a safe navigation bridge to PyQt."""

    view_requested = pyqtSignal(str)
    close_requested = pyqtSignal()

    _NAV_ITEMS = (
        ("timers", "TIME"),
        ("music", "MUSIC"),
        ("news", "NEWS"),
        ("media", "VIDEO"),
        ("system", "SYS"),
    )
    _TITLES = {
        "timers": "TIMERS & REMINDERS",
        "music": "YOUTUBE MUSIC",
        "news": "LIVE NEWS",
        "media": "MEDIA CENTER",
        "system": "SYSTEM STATUS",
        "command": "SMART WINDOW",
    }
    _FALLBACK_CSS = """
        body { margin: 0; padding: 0; background: #0b1519; color: #e8f5f2;
               font-family: 'Segoe UI', sans-serif; }
        .shell { padding: 9px 11px 8px; border-bottom: 1px solid #34545a; }
        .eyebrow { color: #71d4c2; font-size: 8px; font-weight: bold;
                   letter-spacing: 1.4px; }
        .title { color: #edf3e8; font-size: 14px; font-weight: bold; }
        .status { color: #9bd5a2; font-size: 8px; letter-spacing: 1px; }
        .nav { padding-top: 8px; }
        .nav-item { color: #9aafaa; background: #152327; padding: 5px 7px;
                    border: 1px solid #34464a; text-decoration: none;
                    font-size: 8px; font-weight: bold; }
        .nav-item.active { color: #71d4c2; border: 1px solid #71d4c2;
                           background: #172d2c; }
        .close { color: #d98a59; text-decoration: none; font-size: 15px; }
    """
    _FALLBACK_HTML = (
        '<div class="shell"><span class="eyebrow">JARVIS / SMART COMMAND SURFACE</span>'
        '<br/><span class="title">{{TITLE}}</span>'
        '<br/><span class="status">● {{STATUS}}</span>'
        '<a class="close" href="jarvis://close" title="Close smart panel">×</a>'
        '<div class="nav">{{NAV_ITEMS}}</div></div>'
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SmartPanelHeader")
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(116)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.setStyleSheet("QTextBrowser#SmartPanelHeader { background: transparent; border: 0; }")
        self.document().setDocumentMargin(0)
        self.anchorClicked.connect(self._route_link)
        self._template, self._css = self._load_assets()
        self.set_context("command", status="READY")

    @classmethod
    def _load_assets(cls) -> tuple[str, str]:
        asset_dir = Path(__file__).resolve().parent / "assets"
        try:
            template = (asset_dir / "smart_panel.html").read_text(encoding="utf-8")
            css = (asset_dir / "smart_panel.css").read_text(encoding="utf-8")
            if "{{STYLE}}" not in template or "{{NAV_ITEMS}}" not in template:
                raise ValueError("smart panel HTML template is missing required markers")
            return template, css
        except (OSError, ValueError):
            return cls._FALLBACK_HTML, cls._FALLBACK_CSS

    def set_context(self, active: str = "command", *, title: str | None = None,
                    status: str = "READY") -> None:
        """Render the active workspace label and shortcut state."""
        active = active if active in self._TITLES else "command"
        safe_title = html.escape(str(title or self._TITLES[active])[:42])
        safe_status = html.escape(str(status or "READY")[:20].upper())
        nav_items = []
        for key, label in self._NAV_ITEMS:
            selected = " active" if key == active else ""
            nav_items.append(
                f'<a class="nav-item{selected}" href="jarvis://view/{key}">{label}</a>'
            )
        rendered = self._template.replace("{{STYLE}}", self._css)
        rendered = rendered.replace("{{TITLE}}", safe_title)
        rendered = rendered.replace("{{STATUS}}", safe_status)
        rendered = rendered.replace("{{NAV_ITEMS}}", " &nbsp; ".join(nav_items))
        self.setHtml(rendered)

    def _route_link(self, url: QUrl) -> None:
        """Accept only local navigation commands; external links are ignored."""
        if url.scheme().casefold() != "jarvis":
            return
        if url.host().casefold() == "close":
            self.close_requested.emit()
            return
        if url.host().casefold() != "view":
            return
        key = url.path().strip("/").casefold()
        if key in {item[0] for item in self._NAV_ITEMS}:
            self.view_requested.emit(key)
