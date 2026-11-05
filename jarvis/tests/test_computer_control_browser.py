"""Project 3: Browser Controller on a fake browser, cc_browser policy/enrichment,
page content as untrusted data, passwords never exposed, and browser steps in tasks."""
from __future__ import annotations

import json

import pytest

from jarvis.computer_control import approval, audit, estop, flags, runner
from jarvis.computer_control.browser import controller as bc
from jarvis.computer_control.browser.controller import BrowserController, private_destination
from jarvis.computer_control.browser.fake import FakeBrowser
from jarvis.computer_control.orchestrator.host import HostAgent
from jarvis.computer_control.orchestrator.planner import make_plan
from jarvis.computer_control.policy import ActionPolicy, AuthSnapshot, Level
from jarvis.computer_control.runner import ActionContext, ActionRunner
from jarvis.computer_control.tools import build_registry

OWNER = AuthSnapshot(False, True)


def ctx(params=None):
    return ActionContext("test", dict(params or {}), estop.token())


class _Approve:
    def __init__(self, ok=True):
        self.ok, self.asked = ok, []

    def request(self, req, timeout=0):
        self.asked.append(req)
        return approval.ApprovalResult(self.ok, "test", "")


@pytest.fixture
def web(tmp_path, monkeypatch):
    fake = FakeBrowser()
    controller = BrowserController(fake, downloads=str(tmp_path / "dl"))
    bc.set_controller(controller)
    # public-address check without DNS: *.test hosts are "public" here, localhost is not
    monkeypatch.setattr(bc, "private_destination",
                        lambda url: "Local or internal destinations are blocked."
                        if any(h in url for h in ("localhost", "192.168.", "127.0.0.1")) else "")
    from jarvis.computer_control.browser import tools as bt
    monkeypatch.setattr(bt, "private_destination", bc.private_destination)
    monkeypatch.setitem(bc.SEARCH_URLS, "google", "https://search.test/?q=")
    runner.set_runner(ActionRunner(ActionPolicy(auth=lambda: OWNER)))
    estop.reset_for_tests()
    approval.set_approver(None)
    audit.clear_for_tests()
    with flags.override(enabled=True, dry_run=False):
        yield fake, controller
    bc.set_controller(None)
    runner.set_runner(None)


def spec():
    return build_registry().get("cc_browser")


class TestController:
    def test_navigate_verifies_the_site(self, web):
        fake, c = web
        out = c.navigate(ctx(), "news.test")
        assert out.ok and out.verified and out.data["page"]["title"] == "AI News"

    def test_non_web_and_private_urls_are_refused(self, web):
        _fake, c = web
        assert not c.navigate(ctx(), "file:///C:/Windows").ok
        assert "blocked" in c.navigate(ctx(), "http://localhost:8080").message

    def test_search_and_tabs(self, web):
        fake, c = web
        out = c.search(ctx(), "latest AI research")
        assert out.ok and "latest AI research" in out.data["page"]["title"]
        c.new_tab(ctx(), "https://news.test/")
        tabs = c.tabs(ctx())
        assert len(tabs.data["page"]["tabs"]) == 2
        assert c.switch_tab(ctx(), 0).verified
        assert c.close_tab(ctx(), 1).ok and len(fake.tabs) == 1

    def test_snapshot_is_fenced_and_flags_hidden_instructions(self, web):
        _fake, c = web
        c.navigate(ctx(), "https://news.test/")
        read = c.read(ctx())
        assert read.message.startswith("=== BEGIN EXTERNAL CONTENT") and read.data["injection_flags"]
        assert "email your passwords" not in read.message
        snap = c.snapshot(ctx())
        assert "[e1] link" in snap.message and "EXTERNAL CONTENT" in snap.message

    def test_refs_must_come_from_a_fresh_snapshot(self, web):
        _fake, c = web
        c.navigate(ctx(), "https://news.test/")
        assert "snapshot first" in c.click(ctx(), "e1").message
        c.snapshot(ctx())
        assert c.click(ctx(), "e1").ok                     # navigates to /agents
        assert "snapshot" in c.click(ctx(), "e1").message   # page changed: stale

    def test_fill_reads_back_but_never_passwords(self, web):
        fake, c = web
        c.navigate(ctx(), "https://mail.test/login")
        snap = c.snapshot(ctx())
        assert all("value" not in e for e in snap.data["elements"] if e.get("secret"))
        assert c.fill(ctx(), "e1", "owner@mail.test").verified
        context = ctx({"text": "hunter2"})
        out = c.fill(context, "e2", "hunter2")
        assert out.ok and out.verified is None and context.params["is_password"]
        assert "hunter2" not in json.dumps(out.data) and "hunter2" not in out.message

    def test_login_state_awareness(self, web):
        _fake, c = web
        c.navigate(ctx(), "https://mail.test/login")
        assert c.state(ctx()).data["login"] == "login form shown"
        c.snapshot(ctx())
        c.fill(ctx(), "e1", "a@b.test")
        c.fill(ctx(), "e2", "pw")
        c.click(ctx(), "e3")
        assert c.state(ctx()).data["login"] == "signed in"

    def test_click_expectation(self, web):
        _fake, c = web
        c.navigate(ctx(), "https://news.test/")
        c.snapshot(ctx())
        out = c.click(ctx(), "e1", {"expect_url": "/agents"})
        assert out.verified is True

    def test_download_and_upload_verify_files(self, web, tmp_path):
        fake, c = web
        c.navigate(ctx(), "https://news.test/agents")
        c.snapshot(ctx())
        out = c.download(ctx(), "e1")
        assert out.ok and out.verified and out.data["bytes"] > 0
        doc = tmp_path / "cv.pdf"
        doc.write_bytes(b"%PDF")
        c.navigate(ctx(), "https://forms.test/upload")
        c.snapshot(ctx())
        assert c.upload(ctx(), "e1", str(doc)).verified
        assert not c.upload(ctx(), "e1", str(tmp_path / "missing.pdf")).ok
        assert "disabled" in c.click(ctx(), "e2").message

    def test_screenshot_masks_and_saves(self, web):
        fake, c = web
        c.navigate(ctx(), "https://mail.test/login")
        out = c.screenshot(ctx())
        assert out.ok and out.verified and "masked" in out.message

    def test_no_browser_installed(self, tmp_path):
        c = BrowserController(FakeBrowser(available=False))
        out = c.open(ctx())
        assert not out.ok and "Edge/Chrome" in out.message


class TestTool:
    def test_levels(self):
        s = spec()
        assert s.resolve_action({"op": "navigate"}) == "browser.navigate"
        assert s.resolve_action({"op": "upload"}) == "browser.upload"
        assert s.resolve_action({"op": "weird"}) == "unknown"

    def test_read_ops_are_low_and_run(self, web):
        out = spec().call({"op": "navigate", "url": "https://news.test/"})
        assert out.status == "ok" and out.level is Level.LOW

    def test_private_destination_needs_approval(self, web):
        approver = _Approve(True)
        approval.set_approver(approver)
        out = spec().call({"op": "navigate", "url": "http://localhost:3000"})
        assert approver.asked and approver.asked[0].level is Level.HIGH
        assert out.level is Level.HIGH

    def test_private_destination_denied_without_approver(self, web):
        out = spec().call({"op": "navigate", "url": "http://192.168.1.1/admin"})
        assert out.status == "denied"

    def test_checkout_submit_and_card_fields_are_high(self, web):
        fake, c = web
        spec().call({"op": "navigate", "url": "https://shop.test/checkout"})
        spec().call({"op": "snapshot"})
        card = spec().call({"op": "fill", "ref": "e1", "text": "4111111111111111"})
        assert card.status == "denied" and card.level is Level.HIGH
        order = spec().call({"op": "click", "ref": "e3"})            # "Place order"
        assert order.status == "denied" and order.level is Level.HIGH
        assert ("click", "Place order") not in fake.calls

    def test_login_submit_needs_approval_and_password_is_redacted(self, web):
        from jarvis.core import action_log
        fake, _c = web
        approver = _Approve(True)
        approval.set_approver(approver)
        spec().call({"op": "navigate", "url": "https://mail.test/login"})
        spec().call({"op": "snapshot"})
        spec().call({"op": "fill", "ref": "e1", "text": "owner@mail.test"})
        pw = spec().call({"op": "fill", "ref": "e2", "text": "Sup3r-Secret-99"})
        assert pw.status == "ok" and pw.level is Level.MEDIUM
        sign_in = spec().call({"op": "click", "ref": "e3"})
        assert sign_in.level is Level.HIGH and sign_in.status == "ok" and fake.signed_in
        raw = action_log.log_path().read_text(encoding="utf-8")
        assert "Sup3r-Secret-99" not in raw
        assert all("Sup3r-Secret-99" not in json.dumps(r.details) for r in approver.asked)

    def test_upload_is_high(self, web, tmp_path):
        spec().call({"op": "navigate", "url": "https://forms.test/upload"})
        spec().call({"op": "snapshot"})
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert spec().call({"op": "upload", "ref": "e1", "path": str(f)}).status == "denied"

    def test_page_text_is_not_a_command(self, web):
        """A page that says 'email your passwords' cannot trigger a send."""
        fake, _c = web
        spec().call({"op": "navigate", "url": "https://news.test/"})
        read = spec().call({"op": "read"})
        executed = []
        out = runner.get_runner().run_action("message.send", {"to": "x"}, lambda c: executed.append(1),
                                             origin="untrusted")
        assert read.data["injection_flags"] and out.status == "denied" and not executed


class TestTasks:
    def test_open_chrome_and_search(self, web):
        fake, _c = web
        specs = build_registry()
        plan = make_plan("open Chrome and search for the latest AI research", specs)
        assert [s.tool for s in plan.steps] == ["cc_browser", "cc_browser"]
        report = HostAgent(specs).run(plan)
        assert report.success, report.summary
        assert "latest AI research" in fake.page().title

    def test_mixed_browser_and_desktop_agents(self, web):
        from jarvis.computer_control.windows.controller import WindowsController, set_controller
        from jarvis.computer_control.windows.fake import FakeDesktop
        set_controller(WindowsController(FakeDesktop(), launch_timeout=2.0, poll=0.01))
        try:
            specs = build_registry()
            plan = make_plan("search the web for python release notes then open notepad", specs)
            report = HostAgent(specs).run(plan)
            assert report.success, report.summary
            assert [t.agent for t in report.trace] == ["browser", "windows"]
        finally:
            set_controller(None)


def test_real_private_destination_check():
    assert private_destination("http://localhost:8000")
    assert private_destination("http://127.0.0.1/")
    assert private_destination("https://user:pw@example.com/")
