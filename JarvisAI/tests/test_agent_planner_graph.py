"""Tests for bounded planner dependency graphs and deterministic intent routing."""

import json
import unittest
from pathlib import Path

from agent.dependency_graph import DependencyGraphError, topological_sort_steps
from agent.models import Task, TaskStep
from agent.planner import PlanError, TaskPlanner


class DependencyGraphTests(unittest.TestCase):
    def test_forward_dependencies_are_topologically_ordered_and_remapped(self):
        steps = [
            TaskStep(title="dependent", depends_on=[2]),
            TaskStep(title="independent"),
            TaskStep(title="prerequisite"),
        ]

        ordered = topological_sort_steps(steps)

        self.assertEqual(
            [step.title for step in ordered],
            ["independent", "prerequisite", "dependent"],
        )
        self.assertEqual(ordered[2].depends_on, [1])
        self.assertEqual([step.index for step in ordered], [0, 1, 2])

    def test_independent_steps_keep_their_relative_order(self):
        steps = [TaskStep(title="first"), TaskStep(title="second"), TaskStep(title="third")]

        ordered = topological_sort_steps(steps)

        self.assertEqual([step.title for step in ordered], ["first", "second", "third"])

    def test_cycle_is_rejected(self):
        steps = [
            TaskStep(title="first", depends_on=[1]),
            TaskStep(title="second", depends_on=[0]),
        ]

        with self.assertRaisesRegex(DependencyGraphError, "cycle"):
            topological_sort_steps(steps)

    def test_self_dependency_is_rejected(self):
        with self.assertRaisesRegex(DependencyGraphError, "itself"):
            topological_sort_steps([TaskStep(title="self", depends_on=[0])])

    def test_missing_dependency_is_rejected(self):
        with self.assertRaisesRegex(DependencyGraphError, "missing dependency"):
            topological_sort_steps([TaskStep(title="missing", depends_on=[4])])

    def test_task_set_plan_validates_and_orders_dependencies(self):
        task = Task(objective="Execute a dependent plan")
        task.set_plan([
            TaskStep(title="dependent", depends_on=[1]),
            TaskStep(title="prerequisite"),
        ])

        self.assertEqual([step.title for step in task.steps], ["prerequisite", "dependent"])
        self.assertEqual(task.steps[1].depends_on, [0])


class IntelligentPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = TaskPlanner(workspace=Path.cwd())

    def test_model_plan_supports_forward_dependencies(self):
        plan = self.planner.parse(json.dumps({
            "criteria": ["All evidence is collected."],
            "steps": [
                {"title": "Read evidence", "kind": "browser_read", "depends_on": [1]},
                {"title": "Search", "kind": "browser_search", "detail": "public topic"},
                {"title": "Independent note", "kind": "note"},
            ],
        }))

        self.assertEqual(
            [step.title for step in plan.steps],
            ["Search", "Independent note", "Read evidence"],
        )
        self.assertEqual(plan.steps[2].depends_on, [0])

    def test_model_plan_rejects_dependency_cycles(self):
        with self.assertRaisesRegex(PlanError, "dependency graph"):
            self.planner.parse(json.dumps({
                "steps": [
                    {"title": "A", "kind": "note", "depends_on": [1]},
                    {"title": "B", "kind": "note", "depends_on": [0]},
                ],
            }))

    def test_model_plan_rejects_out_of_range_dependencies(self):
        with self.assertRaisesRegex(PlanError, "outside the plan"):
            self.planner.parse(json.dumps({
                "steps": [{"title": "A", "kind": "note", "depends_on": [9]}],
            }))

    def test_deterministic_research_intent_uses_public_search(self):
        plan = self.planner.plan("research Python 3.12 performance improvements")

        self.assertEqual(plan.source, "heuristic")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].kind.value, "browser_search")
        self.assertEqual(
            plan.steps[0].detail,
            "Python 3.12 performance improvements",
        )


    def test_successful_plan_is_cached_and_returned_as_a_copy(self):
        calls = []
        response = json.dumps({
            "criteria": ["done"],
            "steps": [{"title": "cached plan", "kind": "note"}],
        })
        planner = TaskPlanner(
            ask=lambda prompt: calls.append(prompt) or response,
            workspace=Path.cwd(),
            cache_size=4,
        )

        first = planner.plan("prepare a plan")
        first.steps[0].title = "mutated by caller"
        second = planner.plan("prepare a plan")

        self.assertEqual(len(calls), 1)
        self.assertEqual(second.steps[0].title, "cached plan")

    def test_plan_cache_key_includes_acceptance_criteria(self):
        calls = []
        response = json.dumps({"steps": [{"title": "note", "kind": "note"}]})
        planner = TaskPlanner(
            ask=lambda prompt: calls.append(prompt) or response,
            workspace=Path.cwd(),
        )

        planner.plan("same objective", ["criterion A"])
        planner.plan("same objective", ["criterion B"])

        self.assertEqual(len(calls), 2)


    def test_plan_cache_preserves_case_sensitive_url_paths(self):
        calls = []
        response = json.dumps({"steps": [{"title": "case-specific", "kind": "note"}]})
        planner = TaskPlanner(
            ask=lambda prompt: calls.append(prompt) or response,
            workspace=Path.cwd(),
        )
        planner.plan("inspect https://example.com/Docs/Readme")
        planner.plan("inspect https://example.com/docs/readme")
        self.assertEqual(len(calls), 2)

if __name__ == "__main__":
    unittest.main()
