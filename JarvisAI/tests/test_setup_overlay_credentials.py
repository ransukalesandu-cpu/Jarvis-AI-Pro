"""Regression tests for the first-run setup credential prompt.

These AST-level tests intentionally avoid initializing Qt so they can run in
headless CI while verifying the setup dialog asks for and emits only Gemini.
"""
import ast
import unittest
from pathlib import Path


UI_SOURCE = Path(__file__).resolve().parents[1] / "ui" / "__init__.py"


class SetupOverlayCredentialPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(UI_SOURCE.read_text(encoding="utf-8"))
        cls.overlay = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SetupOverlay"
        )

    def test_setup_dialog_exposes_only_gemini_api_key(self):
        init_method = next(
            node for node in self.overlay.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        fields_assignment = next(
            node for node in ast.walk(init_method)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "fields"
                    for target in node.targets)
        )
        self.assertIsInstance(fields_assignment.value, ast.List)
        keys = [
            item.elts[0].value
            for item in fields_assignment.value.elts
            if isinstance(item, ast.Tuple)
            and item.elts
            and isinstance(item.elts[0], ast.Constant)
        ]
        self.assertEqual(keys, ["gemini_api_key"])

    def test_setup_submit_payload_contains_only_gemini_api_key(self):
        submit_method = next(
            node for node in self.overlay.body
            if isinstance(node, ast.FunctionDef) and node.name == "_submit"
        )
        emit_call = next(
            node for node in ast.walk(submit_method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "done"
        )
        payload = emit_call.args[0]
        self.assertIsInstance(payload, ast.Dict)
        keys = [key.value for key in payload.keys if isinstance(key, ast.Constant)]
        self.assertEqual(keys, ["gemini_api_key"])

    def test_setup_window_no_longer_labels_other_provider_keys(self):
        source = ast.get_source_segment(
            UI_SOURCE.read_text(encoding="utf-8"), self.overlay
        )
        self.assertIsNotNone(source)
        for label in ("GROQ API KEY", "OPENAI API KEY", "ANTHROPIC / CLAUDE KEY"):
            self.assertNotIn(label, source)


if __name__ == "__main__":
    unittest.main()
