"""Skills (SKILL.md) and the MCP client, including a real stdio server round-trip."""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.actions import mcp as mcp_tool
from jarvis.actions import skills as skills_tool
from jarvis.core import mcp_client, security, skills
from jarvis.core.skills import SkillError, SkillRegistry, parse_skill_md

GOOD = "---\nname: weekly-report\ndescription: Build the Friday report.\nversion: 2\n---\n# Steps\n1. Do it.\n"

SERVER = textwrap.dedent("""
    try:
        from mcp.server.mcpserver import MCPServer as S
    except ImportError:
        from mcp.server.fastmcp import FastMCP as S
    app = S("demo")

    @app.tool()
    def add(a: int, b: int) -> str:
        \"\"\"Add two numbers.\"\"\"
        return str(a + b)

    @app.tool()
    def leak() -> str:
        \"\"\"Report whether a secret env var reached the server.\"\"\"
        import os
        return "LEAKED" if os.environ.get("GEMINI_API_KEY") else "clean:" + os.environ.get("DEMO_FLAG", "")

    @app.tool()
    def boom() -> str:
        \"\"\"Always fails.\"\"\"
        raise RuntimeError("kaboom")

    if __name__ == "__main__":
        app.run()
""")


class SkillParseTests(unittest.TestCase):
    def test_parse_front_matter_and_body(self):
        meta, body = parse_skill_md(GOOD)
        self.assertEqual((meta["name"], meta["version"]), ("weekly-report", "2"))
        self.assertTrue(body.startswith("# Steps"))

    def test_quotes_and_bom(self):
        meta, _ = parse_skill_md('﻿---\nname: "a"\ndescription: \'x y\'\n---\nbody')
        self.assertEqual((meta["name"], meta["description"]), ("a", "x y"))

    def test_bad_files(self):
        for bad in ("no front matter", "---\nname: a\n", "---\nnot a pair\n---\nbody"):
            with self.assertRaises(SkillError, msg=bad):
                parse_skill_md(bad)


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.builtin = root / "builtin"
        self.user = root / "user"
        self.reg = SkillRegistry(self.user, self.builtin, root / "state.json")

    def _write(self, base: Path, folder: str, text: str):
        (base / folder).mkdir(parents=True, exist_ok=True)
        (base / folder / "SKILL.md").write_text(text, encoding="utf-8")

    def test_scan_user_overrides_builtin_and_reports_errors(self):
        self._write(self.builtin, "weekly-report", GOOD.replace("Build the Friday report.", "builtin"))
        self._write(self.user, "weekly-report", GOOD)
        self._write(self.user, "wrong-name", GOOD)              # name != folder
        self._write(self.user, "no-desc", "---\nname: no-desc\n---\nbody")
        self._write(self.user, "huge", "---\nname: huge\ndescription: d\n---\n" + "x" * 40000)
        found = self.reg.scan()
        self.assertEqual([(s.name, s.source, s.description) for s in found],
                         [("weekly-report", "user", "Build the Friday report.")])
        self.assertEqual(set(self.reg.errors), {"user/wrong-name", "user/no-desc", "user/huge"})

    def test_index_lists_only_enabled_with_descriptions_not_bodies(self):
        self._write(self.user, "weekly-report", GOOD)
        text = self.reg.index_text()
        self.assertIn("weekly-report: Build the Friday report.", text)
        self.assertNotIn("Do it", text)
        self.assertTrue(self.reg.set_enabled("weekly-report", False))
        self.assertEqual(self.reg.index_text(), "")
        self.assertFalse(self.reg.get("weekly-report").enabled)
        self.assertTrue(self.reg.set_enabled("weekly-report", True))
        self.assertTrue(self.reg.get("weekly-report").enabled)
        self.assertFalse(self.reg.set_enabled("missing", True))

    def test_create_delete_and_no_overwrite(self):
        skill = self.reg.create("My_Skill", "Does a thing.", "1. step")
        self.assertEqual(skill.name, "my_skill")
        self.assertIn("created_by: assistant", (self.user / "my_skill" / "SKILL.md").read_text())
        with self.assertRaises(SkillError):
            self.reg.create("my_skill", "again", "2. step")
        self.reg.create("my_skill", "again", "2. step", overwrite=True)
        self.assertEqual(self.reg.get("my_skill").description, "again")
        self.assertTrue(self.reg.delete("my_skill"))
        self.assertFalse(self.reg.delete("my_skill"))
        self.assertFalse((self.user / "my_skill").exists())

    def test_create_validates_and_leaves_nothing_behind(self):
        for args in (("bad name", "d", "b"), ("ok", "", "b"), ("ok", "d", ""), ("ok", "x" * 400, "b")):
            with self.assertRaises(SkillError, msg=args):
                self.reg.create(*args)
        self.assertEqual(list(self.user.glob("*")) if self.user.exists() else [], [])

    def test_cannot_delete_builtin_or_traverse(self):
        self._write(self.builtin, "core-skill", GOOD.replace("weekly-report", "core-skill"))
        self.assertFalse(self.reg.delete("core-skill"))
        self.assertFalse(self.reg.delete("../builtin/core-skill"))
        self.assertIsNotNone(self.reg.get("core-skill"))


class SkillToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        skills.reset_for_tests(SkillRegistry(root / "u", root / "b", root / "s.json"))
        self.addCleanup(skills.reset_for_tests, None)

    def test_flow(self):
        run = skills_tool.skills
        self.assertEqual(run({"action": "list"}), "No skills installed.")
        self.assertIn("saved", run({"action": "create", "name": "daily", "description": "d", "body": "do x"}))
        self.assertIn("daily [user]: d", run({"action": "list"}))
        self.assertIn("do x", run({"action": "use", "name": "daily"}))
        self.assertIn("disabled", run({"action": "disable", "name": "daily"}) + "disabled")
        self.assertIn("is disabled", run({"action": "use", "name": "daily"}))
        self.assertIn("No skill named", run({"action": "use", "name": "nope"}))
        self.assertIn("not saved", run({"action": "create", "name": "Bad Name", "description": "d", "body": "b"}))
        self.assertIn("deleted", run({"action": "delete", "name": "daily"}))

    def test_tiers(self):
        t = security.tier_for
        self.assertEqual(t("skills", {"action": "list"}), security.TIER_SAFE)
        self.assertEqual(t("skills", {"action": "use"}), security.TIER_SAFE)
        self.assertEqual(t("skills", {"action": "create"}), security.TIER_DANGEROUS)
        self.assertEqual(t("skills", {"action": "delete"}), security.TIER_DANGEROUS)
        self.assertEqual(t("skills", {"action": "disable"}), security.TIER_SENSITIVE)


class McpConfigTests(unittest.TestCase):
    def test_load_config_reports_bad_entries_but_keeps_good_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps({"servers": {
                "good": {"command": "python", "args": ["x.py"], "env": {"A": "1"}},
                "bad name!": {"command": "python"},
                "nocmd": {"args": []},
                "off": {"command": "python", "enabled": False}}}), encoding="utf-8")
            servers, problems = mcp_client.load_config(path)
            self.assertEqual(sorted(servers), ["good", "off"])
            self.assertFalse(servers["off"].enabled)
            self.assertEqual(set(problems), {"bad name!", "nocmd"})
            path.write_text("{not json", encoding="utf-8")
            self.assertIn("file", mcp_client.load_config(path)[1])
            self.assertEqual(mcp_client.load_config(Path(tmp) / "missing.json"), ({}, {}))

    def test_format_result_handles_both_sdk_spellings_and_caps(self):
        text = SimpleNamespace(type="text", text="hello")
        image = SimpleNamespace(type="image")
        self.assertEqual(mcp_client.format_result(SimpleNamespace(content=[text, image], is_error=False)),
                         "hello\n[image omitted]")
        self.assertTrue(mcp_client.format_result(SimpleNamespace(content=[text], isError=True))
                        .startswith("MCP tool reported an error"))
        big = SimpleNamespace(type="text", text="x" * 20000)
        self.assertIn("truncated", mcp_client.format_result(SimpleNamespace(content=[big])))
        self.assertEqual(mcp_client.format_result(SimpleNamespace(content=[])), "(no output)")


class McpServerTests(unittest.TestCase):
    """Talks to a real MCP server over stdio."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "server.py").write_text(SERVER, encoding="utf-8")
        cls.config = root / "mcp_servers.json"
        cls.config.write_text(json.dumps({"servers": {
            "demo": {"command": sys.executable, "args": [str(root / "server.py")],
                     "env": {"DEMO_FLAG": "on"}},
            "dead": {"command": sys.executable, "args": ["-c", "import sys; sys.exit(1)"]},
            "off": {"command": sys.executable, "enabled": False}}}), encoding="utf-8")
        cls.manager = mcp_client.McpManager(cls.config)
        mcp_client.reset_for_tests(cls.manager)

    @classmethod
    def tearDownClass(cls):
        mcp_client.reset_for_tests(None)
        cls.tmp.cleanup()

    def test_1_discovery_and_call(self):
        tools = self.manager.list_tools("demo")
        self.assertEqual(sorted(t.name for t in tools), ["add", "boom", "leak"])
        self.assertEqual(self.manager.call("demo", "add", {"a": 2, "b": 3}), "5")
        self.assertIn("add", self.manager.index_text())

    def test_2_server_gets_minimal_environment(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "secret"}):
            mcp_client.get_manager().restart("demo")
            self.assertEqual(self.manager.call("demo", "leak"), "clean:on")

    def test_3_tool_error_is_reported_not_raised(self):
        text = self.manager.call("demo", "boom")
        self.assertTrue(text.startswith("MCP tool reported an error"), text)

    def test_4_unknown_tool_server_and_disabled(self):
        for args in (("demo", "nope"), ("ghost", "x"), ("off", "x")):
            with self.assertRaises(mcp_client.McpError, msg=args):
                self.manager.call(*args)

    def test_5_dead_server_fails_then_is_not_retried_until_restart(self):
        for _ in range(mcp_client.MAX_FAILURES):
            with self.assertRaises(mcp_client.McpError):
                self.manager.connect("dead")
        with self.assertRaises(mcp_client.McpError) as ctx:
            self.manager.connect("dead")
        self.assertIn("restart", str(ctx.exception))
        status = {r["server"]: r["status"] for r in self.manager.status()}
        self.assertEqual((status["dead"], status["off"]), ("failed", "disabled"))

    def test_6_tool_wraps_result_as_untrusted_and_tiers(self):
        out = mcp_tool.mcp({"action": "call", "server": "demo", "tool": "add", "arguments": '{"a": 1, "b": 1}'})
        self.assertIn("BEGIN EXTERNAL CONTENT (source: mcp:demo.add)", out)
        self.assertIn("2", out)
        self.assertIn("JSON object", mcp_tool.mcp({"action": "call", "server": "demo", "tool": "add",
                                                   "arguments": "[1]"}))
        self.assertIn("No tool", mcp_tool.mcp({"action": "describe", "server": "demo", "tool": "zzz"}))
        self.assertIn("input_schema", mcp_tool.mcp({"action": "describe", "server": "demo", "tool": "add"}))
        t = security.tier_for
        self.assertEqual(t("mcp", {"action": "list"}), security.TIER_SAFE)
        # Not marked read-only by the server -> needs confirmation.
        self.assertEqual(t("mcp", {"action": "call", "server": "demo", "tool": "add"}), security.TIER_DANGEROUS)
        self.assertEqual(t("mcp", {"action": "call", "server": "ghost", "tool": "x"}), security.TIER_DANGEROUS)
        self.manager.tool_info("demo", "add").read_only = True
        self.assertEqual(t("mcp", {"action": "call", "server": "demo", "tool": "add"}), security.TIER_SENSITIVE)
        self.manager.tool_info("demo", "add").read_only = False


if __name__ == "__main__":
    unittest.main()
