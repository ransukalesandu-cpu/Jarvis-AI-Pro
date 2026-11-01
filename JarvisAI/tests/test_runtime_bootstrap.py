"""Tests for the dependency-injected JARVIS application bootstrap."""
from __future__ import annotations

from core.runtime.bootstrap import run_application


class _FakeHeadlessUI:
    pass


class _FakeLive:
    def __init__(self, _ui):
        self.ran = False

    async def run(self):
        self.ran = True


def test_headless_bootstrap_runs_injected_live_service():
    created = []

    def live_factory(ui):
        live = _FakeLive(ui)
        created.append((ui, live))
        return live

    result = run_application(
        headless_ui_factory=_FakeHeadlessUI,
        live_factory=live_factory,
        desktop_ui_factory=None,
        argv=["--headless"],
    )

    assert result is None
    assert len(created) == 1
    ui, live = created[0]
    assert isinstance(ui, _FakeHeadlessUI)
    assert live.ran is True


def test_desktop_bootstrap_refuses_missing_ui_without_loading_qt(capsys):
    result = run_application(
        headless_ui_factory=_FakeHeadlessUI,
        live_factory=_FakeLive,
        desktop_ui_factory=None,
        argv=[],
    )

    assert result is None
    assert "desktop UI could not be loaded" in capsys.readouterr().out
