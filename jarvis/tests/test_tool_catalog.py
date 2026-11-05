"""Registry-aware planning, PR A: the read-only local tool catalog."""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

JARVIS_DIR = Path(__file__).resolve().parents[1]
for p in (JARVIS_DIR, JARVIS_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from jarvis.core.action_loader import discover_actions  # noqa: E402
from jarvis.core.tool_catalog import (  # noqa: E402
    MAX_DESCRIPTION_CHARS, ToolCatalog, build_catalog, one_line,
)
from jarvis.core.tool_runtime import ToolMeta  # noqa: E402


class FakeRegistry:
    def __init__(self, decls, metas=None):
        self._decls = decls
        self._metas = metas or {}

    def get_tool_declarations(self):
        return list(self._decls)

    def meta(self, name):
        return self._metas.get(name)


class RemoteToolRegistry(FakeRegistry):      # name matters: it must be skipped
    pass


class HubToolRegistry(FakeRegistry):
    pass


class PluginRegistry(FakeRegistry):
    pass


class Composite:
    def __init__(self, registries):
        self.registries = registries


def decl(name, desc="does a thing", params=None):
    return {"name": name, "description": desc,
            "parameters": params or {"type": "OBJECT", "properties": {}}}


class CatalogTests(unittest.TestCase):
    def test_gathers_inline_actions_and_plugins_sorted(self):
        cat = build_catalog(
            inline=[decl("zeta")],
            registries=[FakeRegistry([decl("beta")]), PluginRegistry([decl("alpha")])],
        )
        self.assertEqual(cat.names(), ["alpha", "beta", "zeta"])
        self.assertEqual(cat.get("zeta").source, "inline")
        self.assertEqual(cat.get("beta").source, "action")
        self.assertEqual(cat.get("alpha").source, "plugin")

    def test_remote_and_hub_registries_are_excluded(self):
        local = FakeRegistry([decl("open_app")])
        comp = Composite([local, HubToolRegistry([decl("hub_tool")]),
                          RemoteToolRegistry([decl("phone_tool")])])
        cat = build_catalog(registries=[comp])
        self.assertEqual(cat.names(), ["open_app"])

    def test_first_declaration_wins_on_collision(self):
        cat = build_catalog(registries=[FakeRegistry([decl("x", "first")]),
                                        FakeRegistry([decl("x", "second")])])
        self.assertEqual(cat.get("x").description, "first")

    def test_long_description_is_flattened_and_capped(self):
        text = "word " * 100 + "\n\n   tail"
        flat = one_line(text)
        self.assertLessEqual(len(flat), MAX_DESCRIPTION_CHARS)
        self.assertNotIn("\n", flat)
        self.assertTrue(flat.endswith("…"))
        self.assertEqual(one_line("  short   text "), "short text")

    def test_risk_and_long_running_come_from_meta(self):
        reg = FakeRegistry([decl("wipe")], {"wipe": ToolMeta(risk="destructive", long_running=True)})
        entry = build_catalog(registries=[reg]).get("wipe")
        self.assertEqual(entry.risk, "destructive")
        self.assertTrue(entry.long_running)

    def test_bad_declarations_and_broken_registries_are_skipped(self):
        class Boom:
            def get_tool_declarations(self):
                raise RuntimeError("nope")

        cat = build_catalog(
            inline=[{"name": "bad name!", "description": "x"}, {"description": "no name"}, decl("good")],
            registries=[Boom(), None],
        )
        self.assertEqual(cat.names(), ["good"])

    def test_schema_is_copied_not_shared(self):
        schema = {"type": "OBJECT", "properties": {"q": {"type": "STRING"}}}
        cat = build_catalog(inline=[decl("t", params=schema)])
        schema["properties"]["q"]["type"] = "CHANGED"
        self.assertEqual(cat.get("t").parameters["properties"]["q"]["type"], "STRING")

    def test_lines_format_and_subset(self):
        cat = build_catalog(inline=[decl("a", "first tool"), decl("b", "second tool")])
        self.assertEqual(cat.lines(), "- a: first tool\n- b: second tool")
        self.assertEqual(cat.lines(["b", "missing"]), "- b: second tool")
        self.assertEqual(len(cat), 2)
        self.assertIn("a", cat)

    def test_empty_catalog(self):
        cat = build_catalog()
        self.assertEqual(len(cat), 0)
        self.assertEqual(cat.lines(), "")
        self.assertIsInstance(cat, ToolCatalog)


class RealRegistryTests(unittest.TestCase):
    def test_hides_unavailable_tools_via_real_action_registry(self):
        src = textwrap.dedent('''
            def run(parameters, **_c):
                return "ok"
            TOOLS = [
                {"name": "visible_tool", "description": "Shown.", "handler": run,
                 "parameters": {"type": "OBJECT", "properties": {}}, "risk": "read"},
                {"name": "hidden_tool", "description": "Hidden.", "handler": run,
                 "parameters": {"type": "OBJECT", "properties": {}},
                 "available": lambda: False},
            ]
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "catalog_probe.py").write_text(src, encoding="utf-8")
            reg = discover_actions(d, logger=lambda _m: None)
            cat = build_catalog(registries=[reg])
        self.assertEqual(cat.names(), ["visible_tool"])
        self.assertEqual(cat.get("visible_tool").risk, "read")


if __name__ == "__main__":
    unittest.main()
