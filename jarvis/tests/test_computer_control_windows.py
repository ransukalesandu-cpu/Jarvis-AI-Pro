"""Project 1 (+6): Windows Controller on the fake desktop, fallback input safeguards,
tool specs through the runner, and the pywinauto backend's pure helpers."""
from __future__ import annotations

import json
import threading

import pytest

from jarvis.computer_control import approval, audit, estop, flags, runner
from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot, Level
from jarvis.computer_control.runner import ActionContext, ActionRunner
from jarvis.computer_control.windows import backend as backend_mod
from jarvis.computer_control.windows.backend import UnavailableBackend
from jarvis.computer_control.windows.controller import WindowsController, set_controller
from jarvis.computer_control.windows.fake import FakeDesktop
from jarvis.computer_control.windows.fallback_input import (
    FallbackInput, InputRefused, Target, average_hash, hamming,
)
from jarvis.computer_control.windows.model import ElementQuery, WindowQuery

OWNER = AuthSnapshot(False, True)


def ctx(params=None, cancel=None) -> ActionContext:
    return ActionContext("test", dict(params or {}), estop.token(cancel))


class FakeDriver:
    name = "fake-driver"

    def __init__(self, size=(1920, 1080)):
        self._size = size
        self.pos = (0, 0)
        self.clicks = []
        self.typed = []
        self.keys = []
        self.screen = {}            # (x, y) -> fingerprint value
        self.changes_on_click = True

    def size(self):
        return self._size

    def position(self):
        return self.pos

    def move(self, x, y):
        self.pos = (x, y)

    def click(self, x, y, button="left", clicks=1):
        self.clicks.append((x, y, button, clicks))
        if self.changes_on_click:
            self.screen[(x, y)] = self.fingerprint(x, y) ^ 0xFFFF

    def drag(self, *a):
        self.clicks.append(("drag",) + a)

    def scroll(self, amount, x=None, y=None):
        self.clicks.append(("scroll", amount))

    def type_text(self, text):
        self.typed.append(text)

    def hotkey(self, keys):
        self.keys.append(tuple(keys))

    def fingerprint(self, x, y, radius=24):
        return self.screen.get((x, y), 0x0F0F0F0F)


@pytest.fixture
def desk():
    fake = FakeDesktop()
    controller = WindowsController(fake, FallbackInput(FakeDriver(), min_interval_s=0.0),
                                   launch_timeout=2.0, poll=0.01)
    set_controller(controller)
    estop.reset_for_tests()
    approval.set_approver(None)
    audit.clear_for_tests()
    yield fake, controller
    set_controller(None)


# ── applications ─────────────────────────────────────────────────────────────
class TestApps:
    def test_discovers_installed_and_running(self, desk):
        fake, c = desk
        out = c.list_installed(ctx())
        assert out.ok and out.data["total"] == 4 and "Notepad" in out.message
        c.launch(ctx(), "Notepad")
        running = c.list_running(ctx())
        assert "notepad.exe" in running.data["apps"] and running.verified

    def test_launch_waits_for_and_verifies_the_window(self, desk):
        fake, c = desk
        fake.slow_launch = 3
        out = c.launch(ctx(), "calculator")
        assert out.ok and out.verified and out.data["window"]["title"] == "Calculator"

    def test_launch_unknown_app_fails_cleanly(self, desk):
        out = desk[1].launch(ctx(), "Photoshop 2099")
        assert not out.ok and "could not find" in out.message

    def test_launch_without_window_is_unverified(self, desk):
        fake, c = desk
        fake.slow_launch = 10_000
        out = c.launch(ctx(), "Notepad")
        assert out.ok and out.verified is False

    def test_app_state(self, desk):
        fake, c = desk
        assert c.app_state(ctx(), "notepad").data["running"] is False
        c.launch(ctx(), "Notepad")
        state = c.app_state(ctx(), "notepad")
        assert state.data["running"] and state.data["active"]

    def test_close_reports_save_dialog_and_never_answers_it(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        c.set_text(ctx(), WindowQuery(title_contains="Notepad"), ElementQuery(control_type="Edit"), "draft")
        out = c.close_app(ctx(), "Notepad")
        assert not out.ok and "save changes" in out.message.lower()
        assert out.data["buttons"] == ["Save", "Don't Save", "Cancel"]
        assert any(w.title == "Untitled - Notepad" for w in fake.windows())   # still open

    def test_close_app_unmodified(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        out = c.close_app(ctx(), "Calculator")
        assert out.ok and out.verified and not fake.windows()

    def test_kill_terminates_only_that_process(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        calc_pid = c.launch(ctx(), "Calculator").data["pid"]
        np_pid = [w.pid for w in fake.windows() if "Notepad" in w.title][0]
        out = c.close_app(ctx(), pid=np_pid, force=True)
        assert out.ok and out.verified
        assert [w.pid for w in fake.windows()] == [calc_pid]


# ── windows ──────────────────────────────────────────────────────────────────
class TestWindows:
    def test_list_activate_states_move(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        c.launch(ctx(), "Calculator")
        assert "Calculator" in c.list_windows(ctx()).message
        q = WindowQuery(title_contains="Notepad")
        assert c.activate(ctx(), q).verified
        assert c.set_state(ctx(), q, "minimize").verified
        assert c.set_state(ctx(), q, "maximize").verified
        assert c.set_state(ctx(), q, "restore").verified
        moved = c.move_resize(ctx(), q, 10, 20, 640, 480)
        assert moved.verified and moved.data["window"]["rect"] == (10, 20, 640, 480)

    def test_move_off_screen_or_tiny_is_refused(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        q = WindowQuery(title_contains="Notepad")
        assert not c.move_resize(ctx(), q, 5000, 0, 400, 300).ok
        assert not c.move_resize(ctx(), q, 0, 0, 20, 20).ok

    def test_ambiguous_window_is_refused(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        c.launch(ctx(), "Notepad")
        c.activate(ctx(), WindowQuery(handle=fake.windows()[0].handle))
        fake._active = None
        out = c.activate(ctx(), WindowQuery(title_contains="Notepad"))
        assert not out.ok and "2 windows match" in out.message

    def test_missing_window(self, desk):
        out = desk[1].activate(ctx(), WindowQuery(title_contains="Excel"))
        assert not out.ok and "No window matches" in out.message

    def test_inspect_lists_controls(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        out = c.inspect_window(ctx(), WindowQuery(title_contains="Calc"))
        assert out.ok and any(e["name"] == "Plus" for e in out.data["elements"])


# ── controls ─────────────────────────────────────────────────────────────────
class TestControls:
    def test_calculator_by_accessibility(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        w = WindowQuery(title_contains="Calculator")
        for name in ("Seven", "Plus", "Five", "Equals"):
            assert c.invoke(ctx(), w, ElementQuery(name=name)).ok
        display = c.read(ctx(), w, ElementQuery(automation_id="CalculatorResults"))
        assert display.data["value"] == "12"
        checked = c.invoke(ctx(), w, ElementQuery(name="Equals"), {"expect_text": "Display is 12"})
        assert checked.verified is True

    def test_click_without_expectation_is_unchecked(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        out = c.invoke(ctx(), WindowQuery(title_contains="Calc"), ElementQuery(name="One"))
        assert out.ok and out.verified is None

    def test_failed_expectation_is_reported(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        out = c.invoke(ctx(), WindowQuery(title_contains="Calc"), ElementQuery(name="One"),
                       {"expect_window": "Never Appears", "expect_timeout": 0.2})
        assert out.verified is False

    def test_set_text_reads_back(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        out = c.set_text(ctx(), WindowQuery(title_contains="Notepad"), ElementQuery(control_type="Edit"),
                         "Hello from JARVIS")
        assert out.verified and fake.element_named("Notepad", "Text Editor").value == "Hello from JARVIS"

    def test_disabled_control_is_unavailable(self, desk):
        fake, c = desk
        c.launch(ctx(), "Settings App")
        out = c.invoke(ctx(), WindowQuery(title_contains="Settings"), ElementQuery(name="Apply"))
        assert not out.ok and "disabled" in out.message and "unavailable" in out.message

    def test_missing_control(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        out = c.invoke(ctx(), WindowQuery(title_contains="Calc"), ElementQuery(name="Square root"))
        assert not out.ok and "No control" in out.message

    def test_ambiguous_control_needs_an_index(self, desk):
        fake, c = desk
        c.launch(ctx(), "Settings App")
        w = WindowQuery(title_contains="Settings")
        out = c.invoke(ctx(), w, ElementQuery(name="OK"))
        assert not out.ok and "2 controls match" in out.message
        assert c.invoke(ctx(), w, ElementQuery(name="OK", index=1)).ok

    def test_select_and_toggle_verify(self, desk):
        fake, c = desk
        c.launch(ctx(), "Contoso Login")
        w = WindowQuery(title_contains="Contoso")
        assert c.select(ctx(), w, ElementQuery(name="Theme"), "Dark").verified
        assert not c.select(ctx(), w, ElementQuery(name="Theme"), "Purple").ok
        assert c.toggle(ctx(), w, ElementQuery(name="Remember me")).data["state"] == "on"

    def test_password_field_is_never_read_and_is_flagged(self, desk):
        fake, c = desk
        c.launch(ctx(), "Contoso Login")
        w = WindowQuery(title_contains="Contoso")
        context = ctx({"text": "s3cret!"})
        out = c.set_text(context, w, ElementQuery(name="Password"), "s3cret!")
        assert out.ok and out.verified is None and context.params["is_password"] is True
        assert "s3cret" not in json.dumps(out.data)
        read = c.read(ctx(), w, ElementQuery(name="Password"))
        assert "never read" in read.message and read.data["element"]["value"] is None
        assert fake.password_length(f"{fake.windows()[0].handle}:1") == 7
        listed = c.find(ctx(), w, ElementQuery())
        assert all(e["value"] is None for e in listed.data["elements"] if e["is_password"])

    def test_menu_and_hotkey(self, desk, tmp_path):
        fake, c = desk
        path = str(tmp_path / "note.txt")
        c.launch(ctx(), "Notepad", [path])
        w = WindowQuery(title_contains="note.txt")
        c.set_text(ctx(), w, ElementQuery(control_type="Edit"), "v1")
        assert c.menu(ctx(), w, "File->Save").ok and fake.files[path] == "v1"
        c.set_text(ctx(), w, ElementQuery(control_type="Edit"), "v2")
        assert c.hotkey(ctx(), w, ["ctrl", "s"]).ok and fake.files[path] == "v2"
        assert not c.menu(ctx(), w, "File->Teleport").ok

    def test_wait_element_and_stop(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        cancel = threading.Event()
        threading.Timer(0.05, cancel.set).start()
        with pytest.raises(estop.EmergencyStopped):
            c.wait_element(ctx(cancel=cancel), WindowQuery(title_contains="Calc"),
                           ElementQuery(name="Never"), timeout=5)


# ── fallback input safeguards (Project 6) ────────────────────────────────────
class TestFallbackInput:
    def fb(self, **kw):
        return FallbackInput(FakeDriver(), min_interval_s=0.0, **kw)

    def test_rejects_off_screen_and_corners(self):
        fb = self.fb()
        for x, y in ((-1, 5), (5000, 10), (0, 0), (1919, 1079), (2, 1077)):
            with pytest.raises(InputRefused):
                fb.validate_point(x, y)
        assert fb.validate_point(500, 400) == (500, 400)

    def test_owner_coordinates_click_and_verify(self):
        fb = self.fb()
        out = fb.click(ctx(), Target(500, 400, source="owner"))
        assert out.ok and out.verified is True and fb.driver.clicks == [(500, 400, "left", 1)]

    def test_ai_coordinates_need_confidence_and_fingerprint(self):
        fb = self.fb()
        with pytest.raises(InputRefused, match="Not sure"):
            fb.click(ctx(), Target(500, 400, source="vision", confidence=0.5, fingerprint=0x0F0F0F0F))
        with pytest.raises(InputRefused, match="fingerprint"):
            fb.click(ctx(), Target(500, 400, source="model", confidence=0.95))
        assert fb.driver.clicks == []
        assert fb.click(ctx(), Target(500, 400, source="vision", confidence=0.95,
                                      fingerprint=0x0F0F0F0F)).ok

    def test_screen_change_since_locating_is_refused(self):
        fb = self.fb()
        fb.driver.screen[(500, 400)] = 0x0F0F0F0F ^ 0xFFFFFFFF   # the screen moved on
        with pytest.raises(InputRefused, match="changed"):
            fb.click(ctx(), Target(500, 400, source="vision", confidence=0.99, fingerprint=0x0F0F0F0F))
        assert fb.driver.clicks == []

    def test_click_storm_is_prevented(self):
        now = [0.0]
        fb = FallbackInput(FakeDriver(), max_actions=3, window_s=2.0, min_interval_s=0.1,
                           clock=lambda: now[0])
        for i in range(3):
            now[0] += 0.2
            fb.click(ctx(), Target(300 + i, 300, source="owner"))
        now[0] += 0.2
        with pytest.raises(InputRefused, match="click storm"):
            fb.click(ctx(), Target(400, 300, source="owner"))
        now[0] += 0.01
        fb2 = FallbackInput(FakeDriver(), min_interval_s=0.5, clock=lambda: now[0])
        fb2.click(ctx(), Target(300, 300, source="owner"))
        with pytest.raises(InputRefused, match="too fast"):
            fb2.click(ctx(), Target(310, 300, source="owner"))

    def test_typing_is_chunked_and_stoppable(self):
        fb = self.fb()
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(estop.EmergencyStopped):
            fb.type_text(ctx(cancel=cancel), "x" * 1000)
        assert fb.driver.typed == []
        fb.type_text(ctx(), "y" * 450)
        assert [len(t) for t in fb.driver.typed] == [200, 200, 50]

    def test_average_hash(self):
        flat = bytes([128] * 64 * 64)
        half = bytes(([0] * 32 + [255] * 32) * 64)
        assert hamming(average_hash(flat, 64, 64), average_hash(half, 64, 64)) > 10
        assert average_hash(half, 64, 64) == average_hash(half, 64, 64)


# ── tools through the runner (policy, enrichment, audit) ─────────────────────
class TestTools:
    @pytest.fixture(autouse=True)
    def _on(self, desk):
        runner.set_runner(ActionRunner(ActionPolicy(auth=lambda: OWNER)))
        with flags.override(enabled=True, dry_run=False):
            yield
        runner.set_runner(None)

    def spec(self, tool_id):
        from jarvis.computer_control.tools import build_registry
        return build_registry().get(tool_id)

    def test_tools_are_registered(self):
        from jarvis.computer_control.tools import build_registry
        ids = {s.id for s in build_registry().specs()}
        assert {"cc_app", "cc_window", "cc_control", "cc_pointer"} <= ids

    def test_op_levels(self):
        app = self.spec("cc_app")
        assert app.resolve_action({"op": "launch"}) == "app.launch"
        assert app.resolve_action({"op": "kill"}) == "app.kill"
        assert app.resolve_action({"op": "nonsense"}) == "unknown"

    def test_launch_and_type_end_to_end(self, desk):
        fake, _c = desk
        result = self.spec("cc_app").call({"op": "launch", "name": "Notepad"})
        assert result.status == "ok" and result.verified and result.level is Level.LOW
        typed = self.spec("cc_control").call({"op": "set_text", "window": "Notepad",
                                              "control_type": "Edit", "text": "hi"})
        assert typed.status == "ok" and typed.verified and typed.level is Level.MEDIUM

    def test_kill_needs_approval(self, desk):
        fake, _c = desk
        self.spec("cc_app").call({"op": "launch", "name": "Notepad"})
        pid = fake.windows()[0].pid
        result = self.spec("cc_app").call({"op": "kill", "pid": pid})
        assert result.status == "denied" and fake.windows()

    def test_destructive_button_by_ref_is_high(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        c.set_text(ctx(), WindowQuery(title_contains="Notepad"), ElementQuery(control_type="Edit"), "x")
        c.close_window(ctx(), WindowQuery(title_contains="Notepad"))
        dialog = [w for w in fake.windows() if w.class_name == "#32770"][0]
        ref = [e.ref for e in fake.elements(dialog.handle) if e.name == "Don't Save"][0]
        # given only a ref, enrichment adds the real name "Don't Save"... which is not destructive;
        # the "Delete"-style check uses the real label, so a ref cannot hide one:
        fake.element_named("Notepad", "Save").name = "Delete file"
        bad_ref = [e.ref for e in fake.elements(dialog.handle) if e.name == "Delete file"][0]
        result = self.spec("cc_control").call({"op": "invoke", "handle": dialog.handle, "ref": bad_ref})
        assert result.status == "denied" and result.level is Level.HIGH
        ok = self.spec("cc_control").call({"op": "invoke", "handle": dialog.handle, "ref": ref})
        assert ok.status == "ok"

    def test_typing_into_a_shell_window_needs_approval(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        handle = fake.windows()[0].handle
        fake.rename_window(handle, "Administrator: Windows PowerShell")
        result = self.spec("cc_control").call({"op": "type", "text": "Remove-Item C:\\ -Recurse"})
        assert result.status == "denied" and result.level is Level.HIGH
        assert fake.sent_text == []

    def test_password_text_is_not_in_the_action_log(self, desk):
        from jarvis.core import action_log
        self.spec("cc_app").call({"op": "launch", "name": "Contoso Login"})
        self.spec("cc_control").call({"op": "set_text", "window": "Contoso", "name": "Password",
                                      "text": "Pa55w0rd-XYZ"})
        raw = action_log.log_path().read_text(encoding="utf-8")
        assert "Pa55w0rd-XYZ" not in raw and "[password-field]" in raw

    def test_pointer_clicks_from_the_model_need_approval(self):
        result = self.spec("cc_pointer").call({"op": "click", "x": 500, "y": 400, "source": "owner"})
        assert result.status == "denied" and result.level is Level.HIGH

    def test_pointer_safeguards_still_apply_after_approval(self):
        class Yes:
            def request(self, req, timeout=0):
                return approval.ApprovalResult(True, "test", "")
        approval.set_approver(Yes())
        low = self.spec("cc_pointer").call({"op": "click", "x": 500, "y": 400, "source": "vision",
                                            "confidence": 0.3, "fingerprint": 1})
        assert low.status == "failed" and "Not sure" in low.message
        # a model claiming source="owner" is treated as the model: a fingerprint is required
        claimed = self.spec("cc_pointer").call({"op": "click", "x": 500, "y": 400, "source": "owner"})
        assert claimed.status == "failed" and "fingerprint" in claimed.message

    def test_pointer_typing_sees_the_focused_window(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        fake.rename_window(fake.windows()[0].handle, "Windows PowerShell")
        typed = self.spec("cc_pointer").call({"op": "type", "text": "Remove-Item C:\\ -Recurse"})
        assert typed.status == "denied" and typed.level is Level.HIGH

    def test_emergency_stop_reaches_a_waiting_control_op(self, desk):
        fake, c = desk
        c.launch(ctx(), "Calculator")
        holder = {}
        t = threading.Thread(target=lambda: holder.setdefault("r", self.spec("cc_control").call(
            {"op": "wait", "window": "Calc", "name": "Never", "timeout": 20})))
        t.start()
        import time
        time.sleep(0.1)
        estop.trigger("test")
        t.join(3)
        assert holder["r"].status == "cancelled"


# ── backend selection and pywinauto helpers ──────────────────────────────────
class TestReviewFixes:
    def test_window_handle_zero_is_not_the_active_window(self, desk):
        fake, c = desk
        c.launch(ctx(), "Notepad")
        assert not WindowQuery(handle=0).empty() and not WindowQuery(pid=0).empty()
        out = c.activate(ctx(), WindowQuery(handle=0))
        assert not out.ok and "No window matches" in out.message

    def test_close_app_without_windows_is_not_a_success(self, desk):
        fake, c = desk
        pid = fake.launch("notepad.exe", [])
        for handle in [w.handle for w in fake.windows()]:
            fake._windows.pop(handle)
        out = c.close_app(ctx(), pid=pid)
        assert not out.ok and "no window" in out.message

    def test_click_verification_uses_a_fresh_baseline(self):
        driver = FakeDriver()
        driver.changes_on_click = False
        fb = FallbackInput(driver, min_interval_s=0.0, max_hash_distance=8)
        driver.screen[(500, 400)] = 0x0F0F0F0F ^ 0b11          # ambient drift since locating
        out = fb.click(ctx(), Target(500, 400, source="vision", confidence=0.95, fingerprint=0x0F0F0F0F))
        assert out.ok and out.verified is None                 # drift alone is not "the click worked"

    def test_enrichment_does_not_touch_the_desktop_when_disabled(self, desk):
        from jarvis.computer_control.tools import build_registry
        fake, _c = desk
        calls = []
        fake.windows_orig = fake.windows
        fake.windows = lambda: calls.append(1) or fake.windows_orig()
        with flags.override(enabled=False):
            out = build_registry().get("cc_control").call({"op": "click", "window": "Notepad", "name": "OK"})
        assert out.status == "disabled" and calls == []


class TestBackend:
    def test_non_windows_is_unavailable_with_a_reason(self, monkeypatch):
        monkeypatch.setattr(backend_mod.platform, "system", lambda: "Linux")
        backend_mod.set_backend(None)
        b = backend_mod.get_backend()
        assert isinstance(b, UnavailableBackend) and not b.available()[0]
        with pytest.raises(backend_mod.BackendUnavailable):
            b.windows()
        try:
            with pytest.raises(backend_mod.BackendUnavailable):
                WindowsController(b).list_windows(ctx())
        finally:
            backend_mod.set_backend(None)

    def test_send_keys_escaping(self):
        from jarvis.computer_control.windows.uia import escape_send_keys, hotkey_to_send_keys
        assert escape_send_keys("a+b (c)%") == "a{+}b {(}c{)}{%}"
        assert escape_send_keys("x\ny") == "x{ENTER}y"
        assert hotkey_to_send_keys(["ctrl", "s"]) == "{VK_CONTROL down}s{VK_CONTROL up}"
        assert hotkey_to_send_keys(["ctrl", "shift", "esc"]) == \
            "{VK_CONTROL down}{VK_SHIFT down}{ESC}{VK_SHIFT up}{VK_CONTROL up}"
        from jarvis.computer_control.windows.backend import BackendError
        with pytest.raises(BackendError):
            hotkey_to_send_keys(["hyper", "x"])


def test_menu_label_and_path_helpers():
    from jarvis.computer_control.windows.uia import menu_label, split_menu_path
    assert menu_label("&Save\tCtrl+S") == "save"
    assert menu_label("Save &As...") == "save as"
    assert split_menu_path("File->Save As") == ["File", "Save As"]
    assert split_menu_path("Format > Font") == ["Format", "Font"]
