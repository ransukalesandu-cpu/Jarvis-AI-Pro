"""Regression tests for the authenticated, read-only browser task steps."""
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from agent.executor import ExecutionContext, StepExecutor
from agent.models import StepKind, Task, TaskStep
from agent.planner import PlanError, TaskPlanner
from agent.policy import ExecutionPolicy, PolicyEngine, Risk, classify_step


class AgentBrowserStepTests(unittest.TestCase):
    def setUp(self):
        self.browser = Mock()
        self.browser.search_web.return_value = {
            "title": "Search results",
            "url": "https://example.com/search",
            "text": "A result from the page",
        }
        self.browser.navigate.return_value = {
            "title": "Example",
            "url": "https://example.com/",
            "text": "Example page",
        }
        self.browser.read_page.return_value = {
            "title": "Current page",
            "url": "https://example.com/current",
            "text": "Current content",
        }
        self.browser.click_link.return_value = {
            "title": "Linked page",
            "url": "https://example.com/linked",
            "text": "Linked content",
        }
        self.policy = ExecutionPolicy(allowed_risk=Risk.READ, allow_network=True)
        self.executor = StepExecutor(
            engine=PolicyEngine(self.policy, owner_check=lambda: False)
        )
        self.ctx = ExecutionContext(
            task=Task(objective="Inspect a public web page"),
            workspace=Path.cwd(),
            cancel=threading.Event(),
            pause=threading.Event(),
            browser=self.browser,
            policy=self.policy,
        )

    def test_browser_search_returns_untrusted_page_evidence(self):
        step = TaskStep(
            title="Search the web", kind=StepKind.BROWSER_SEARCH,
            detail="public information",
        )
        result = self.executor.execute(step, self.ctx)
        self.browser.search_web.assert_called_once_with("public information")
        self.assertTrue(result.ok)
        self.assertIn("UNTRUSTED WEB PAGE CONTENT", result.output)
        self.assertEqual(result.evidence["url"], "https://example.com/search")

    def test_navigation_read_and_follow_link_use_narrow_browser_methods(self):
        cases = [
            (TaskStep(title="Open", kind=StepKind.BROWSER_NAVIGATE,
                      detail="https://example.com"), "navigate"),
            (TaskStep(title="Read", kind=StepKind.BROWSER_READ), "read_page"),
            (TaskStep(title="Follow", kind=StepKind.BROWSER_FOLLOW_LINK,
                      target="About"), "click_link"),
        ]
        for step, method in cases:
            with self.subTest(kind=step.kind):
                result = self.executor.execute(step, self.ctx)
                self.assertTrue(result.ok)
                getattr(self.browser, method).assert_called()

    def test_browser_steps_are_read_only_by_default(self):
        for kind in (
            StepKind.BROWSER_SEARCH, StepKind.BROWSER_NAVIGATE,
            StepKind.BROWSER_READ, StepKind.BROWSER_FOLLOW_LINK,
        ):
            step = TaskStep(title="Read web", kind=kind, detail="query")
            risk, _ = classify_step(step)
            self.assertIs(risk, Risk.READ)

    def test_network_policy_blocks_browser_before_touching_browser(self):
        self.ctx.policy.allow_network = False
        result = self.executor.execute(
            TaskStep(title="Search", kind=StepKind.BROWSER_SEARCH, detail="query"),
            self.ctx,
        )
        self.assertTrue(result.blocked)
        self.browser.search_web.assert_not_called()

    def test_missing_browser_fails_closed(self):
        self.ctx.browser = None
        result = self.executor.execute(
            TaskStep(title="Read", kind=StepKind.BROWSER_READ), self.ctx
        )
        self.assertTrue(result.blocked)

    def test_planner_accepts_typed_browser_steps_and_round_trips(self):
        planner = TaskPlanner(workspace=Path.cwd())
        plan = planner.parse(json.dumps({
            "steps": [
                {"title": "Search", "kind": "browser_search", "detail": "public topic"},
                {"title": "Open", "kind": "browser_navigate",
                 "detail": "https://example.com"},
                {"title": "Read", "kind": "browser_read"},
                {"title": "Follow", "kind": "browser_follow_link", "target": "About"},
            ]
        }))
        self.assertEqual(
            [step.kind for step in plan.steps],
            [StepKind.BROWSER_SEARCH, StepKind.BROWSER_NAVIGATE,
             StepKind.BROWSER_READ, StepKind.BROWSER_FOLLOW_LINK],
        )
        restored = TaskStep.from_dict(plan.steps[0].to_dict())
        self.assertIs(restored.kind, StepKind.BROWSER_SEARCH)
        self.assertEqual(restored.detail, "public topic")

    def test_planner_rejects_browser_steps_without_required_input(self):
        planner = TaskPlanner(workspace=Path.cwd())
        with self.assertRaises(PlanError):
            planner.parse(json.dumps({
                "steps": [{"title": "Search", "kind": "browser_search"}]
            }))

    def test_deterministic_planner_supports_browser_without_api_key(self):
        planner = TaskPlanner(workspace=Path.cwd())
        search = planner.plan("search the web for Python documentation")
        self.assertEqual(search.source, "heuristic")
        self.assertIs(search.steps[0].kind, StepKind.BROWSER_SEARCH)
        self.assertEqual(search.steps[0].detail, "Python documentation")

        navigate = planner.plan("open https://example.com/docs")
        self.assertIs(navigate.steps[0].kind, StepKind.BROWSER_NAVIGATE)
        self.assertEqual(navigate.steps[0].detail, "https://example.com/docs")

        read_page = planner.plan("read current page")
        self.assertIs(read_page.steps[0].kind, StepKind.BROWSER_READ)

        follow = planner.plan("follow link named About")
        self.assertIs(follow.steps[0].kind, StepKind.BROWSER_FOLLOW_LINK)
        self.assertEqual(follow.steps[0].target, "About")


if __name__ == "__main__":
    unittest.main()
