"""Security V2 Phase 6: static guards that keep the design from regressing."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "jarvis"
SENSITIVE_MODULES = ["core/identity.py", "core/owner_registry.py", "core/guest_audit.py", "core/guest_session.py",
                     "core/security_settings.py", "core/security_view.py", "actions/guest_history.py",
                     "actions/security_settings.py", "ui/panels/guest_security_view.py"]


def _app_files():
    for path in PKG.rglob("*"):
        if path.suffix in {".py", ".js", ".html", ".json", ".ts"} and "tests" not in path.parts and "__pycache__" not in path.parts:
            yield path


class NoServiceRoleInDesktopApp(unittest.TestCase):
    def test_no_service_role_key_in_python_or_web_assets(self):
        bad = [str(p.relative_to(ROOT)) for p in _app_files()
               if re.search(r"service_role|SERVICE_ROLE", p.read_text(encoding="utf-8", errors="ignore"))]
        self.assertEqual(bad, [], "service-role credentials must never be referenced by the desktop app")


class NoSecretLoggingInSecurityModules(unittest.TestCase):
    def test_no_print_or_logging_in_security_modules(self):
        for rel in SENSITIVE_MODULES:
            src = (PKG / rel).read_text(encoding="utf-8")
            with self.subTest(module=rel):
                self.assertNotRegex(src, r"\bprint\(", rel)
                self.assertNotRegex(src, r"\blogging\b|\blogger\.", rel)

    def test_no_plaintext_pin_columns(self):
        src = (PKG / "core/owner_registry.py").read_text(encoding="utf-8")
        self.assertIn("pin_hash", src)
        self.assertNotRegex(src, r"\bpin\s+TEXT\b|\bpassword\s+TEXT\b", "owner table must store hashes only")

    def test_pins_never_pass_through_voice_or_model_paths(self):
        for rel in ("core/guest_session.py", "core/owner_registry.py"):
            src = (PKG / rel).read_text(encoding="utf-8")
            with self.subTest(module=rel):
                for forbidden in ("genai", "gemini", "websocket", "requests", "urllib", "httpx"):
                    self.assertNotIn(forbidden, src.lower())


class SecurityToolsAreOwnerOnly(unittest.TestCase):
    def test_security_tools_are_dangerous_tier_and_off_the_guest_allowlist(self):
        from jarvis.core import identity, security
        # jarvis_settings and files are tiered by action (Phase 1 tests cover that); the three
        # below are DANGEROUS for every call.
        for tool in ("guest_history", "security_settings", "run_command"):
            with self.subTest(tool=tool):
                self.assertEqual(security.tier_for(tool, {}), security.TIER_DANGEROUS)
        for tool in ("guest_history", "security_settings", "run_command", "jarvis_settings", "files"):
            with self.subTest(allowlist=tool):
                self.assertNotIn(tool, identity.GUEST_ALLOWED_TOOLS)

    def test_guest_allowlist_is_small_and_all_safe(self):
        from jarvis.core import identity, security
        self.assertLessEqual(len(identity.GUEST_ALLOWED_TOOLS), 5)
        for tool in identity.GUEST_ALLOWED_TOOLS:
            self.assertEqual(security.tier_for(tool, {}), security.TIER_SAFE)


class WorkflowsArePinned(unittest.TestCase):
    def test_security_workflow_pins_third_party_actions_to_shas(self):
        text = (ROOT / ".github/workflows/security-scan.yml").read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*([^\s#]+)", text)
        self.assertTrue(uses)
        for ref in uses:
            with self.subTest(ref=ref):
                self.assertRegex(ref, r"@[0-9a-f]{40}$")

    def test_security_workflow_has_least_privilege_default(self):
        text = (ROOT / ".github/workflows/security-scan.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"permissions:\s*\n\s+contents: read")


if __name__ == "__main__":
    unittest.main()
