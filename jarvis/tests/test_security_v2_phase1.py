"""Security V2 Phase 1: identity/session model, guest default-deny, task-password separation,
and a completeness ratchet over every registered action's risk tier."""
from __future__ import annotations

import ast
import dataclasses
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.core import identity, security
from jarvis.core.identity import (
    GUEST, OWNER_AUTHENTICATED, OWNER_AUTHENTICATING, REVOKED, ROLE_GUEST, ROLE_OWNER,
    SESSION_EXPIRED, STEP_UP_REQUIRED, IdentityError, IdentityManager, mint_owner_proof,
)

ACTIONS = Path(__file__).resolve().parents[1] / "actions"


def static_action_names() -> dict[str, str]:
    """Tool names declared by actions/*.py, read from source (no imports, no display needed)."""
    found: dict[str, str] = {}
    for path in sorted(ACTIONS.glob("*.py")):
        if path.name.startswith("_"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
                name = keys.get("name")
                if "handler" in keys and isinstance(name, ast.Constant) and isinstance(name.value, str):
                    found[name.value] = path.name
    return found


# Tools that intentionally use the SENSITIVE default (reviewed in docs/SECURITY_V2_AUDIT.md).
# A new tool must either get an explicit tier in security.py or be added here on purpose.
REVIEWED_DEFAULT_SENSITIVE = {
    "ask_claude", "auto_repair", "calendar", "change_personality", "desktop_automation", "facts",
    "generate_media", "job_status", "play_music", "proactive_triggers", "routine", "rules",
    "see_camera", "see_screen", "show_recent_actions", "start_job", "system_info",
}


class TierCompletenessTests(unittest.TestCase):
    def test_every_action_has_an_explicit_or_reviewed_tier(self):
        names = static_action_names()
        self.assertGreater(len(names), 40)
        source = inspect.getsource(security.tier_for)
        handled = set(security._TIERS) | {n for n in names if f'"{n}"' in source}
        unreviewed = sorted(set(names) - handled - REVIEWED_DEFAULT_SENSITIVE)
        self.assertEqual(unreviewed, [], "new tools need an explicit tier in core/security.py")

    def test_pc_tools_no_longer_default_to_sensitive(self):
        tier = security.tier_for
        self.assertEqual(tier("run_command", {"command": "x"}), security.TIER_DANGEROUS)
        self.assertEqual(tier("ui_automate", {}), security.TIER_DANGEROUS)
        self.assertEqual(tier("open", {}), security.TIER_DANGEROUS)
        for action in ("write", "move", "copy", "delete", "unknown-op"):
            self.assertEqual(tier("files", {"action": action}), security.TIER_DANGEROUS, action)
        for action in ("search", "read", "list"):
            self.assertEqual(tier("files", {"action": action}), security.TIER_SAFE, action)
        self.assertEqual(tier("software", {"action": "uninstall"}), security.TIER_DANGEROUS)
        self.assertEqual(tier("software", {"action": "list"}), security.TIER_SAFE)
        self.assertEqual(tier("email", {"action": "send"}), security.TIER_DANGEROUS)
        self.assertEqual(tier("jarvis_settings", {"operation": "set"}), security.TIER_DANGEROUS)


class StateMachineTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.m = IdentityManager(clock=lambda: self.now[0])

    def owner(self, owner_id="owner-1", strength=1):
        self.m.begin_owner_auth()
        return self.m.complete_owner_auth(mint_owner_proof(owner_id, "pin", strength=strength))

    def test_starts_unauthenticated_and_guest_is_explicit(self):
        self.assertFalse(self.m.guest_mode_active())
        s = self.m.start_guest()
        self.assertEqual((s.role, s.state), (ROLE_GUEST, GUEST))
        self.assertTrue(self.m.guest_mode_active())

    def test_only_a_real_proof_creates_an_owner_session(self):
        self.m.start_guest()
        for fake in (None, "owner", {"owner_id": "x"}, object()):
            with self.assertRaises(IdentityError):
                self.m.complete_owner_auth(fake)  # type: ignore[arg-type]
        self.assertEqual(self.m.current().role, ROLE_GUEST)
        with self.assertRaises(IdentityError):                       # skipping begin_owner_auth
            self.m.complete_owner_auth(mint_owner_proof("o", "pin"))
        with self.assertRaises(IdentityError):
            mint_owner_proof("o", "task-password")

    def test_owner_session_and_two_owners_are_independent(self):
        s1 = self.owner("a")
        self.assertEqual((s1.role, s1.state, s1.owner_id), (ROLE_OWNER, OWNER_AUTHENTICATED, "a"))
        s2 = self.owner("b") if self.m.current().state == OWNER_AUTHENTICATING else None
        self.assertIsNone(s2)                                         # can't jump owner->owner silently
        self.m.end_session()
        s3 = self.owner("b")
        self.assertEqual(s3.owner_id, "b")
        self.assertNotEqual(s1.session_id, s3.session_id)

    def test_expiry_returns_to_guest_level(self):
        self.owner()
        self.now[0] += identity.OWNER_SESSION_SECONDS + 1
        s = self.m.current()
        self.assertEqual((s.role, s.state), (ROLE_GUEST, SESSION_EXPIRED))
        self.assertFalse(self.m.authorize("run_command", "DANGEROUS").allowed)

    def test_revocation_ends_access_and_blocks_reauth(self):
        self.owner("a")
        self.m.revoke_owner("a")
        self.assertEqual(self.m.current().state, REVOKED)
        self.assertFalse(self.m.authorize("files", "SAFE").allowed)
        with self.assertRaises(IdentityError):                        # REVOKED cannot jump to auth
            self.m.begin_owner_auth()
        self.m.end_session()                                          # back to a clean slate...
        self.m.begin_owner_auth()
        with self.assertRaises(IdentityError):                        # ...but the revoked owner stays out
            self.m.complete_owner_auth(mint_owner_proof("a", "pin"))
        self.assertNotEqual(self.m.current().role, ROLE_OWNER)

    def test_step_up_gate(self):
        self.owner("a", strength=1)
        self.assertTrue(self.m.authorize("files", "SAFE").allowed)
        self.assertFalse(self.m.authorize("run_command", "DANGEROUS", needs_strong=True).allowed)
        self.m.require_step_up()
        self.assertEqual(self.m.current().state, STEP_UP_REQUIRED)
        self.assertFalse(self.m.authorize("files", "SAFE").allowed)
        with self.assertRaises(IdentityError):
            self.m.complete_step_up(mint_owner_proof("someone-else", "pin"))
        self.m.complete_step_up(mint_owner_proof("a", "pin"))
        self.assertTrue(self.m.authorize("run_command", "DANGEROUS", needs_strong=True).allowed)
        self.now[0] += identity.STEP_UP_WINDOW_SECONDS + 1
        self.assertFalse(self.m.authorize("run_command", "DANGEROUS", needs_strong=True).allowed)

    def test_illegal_transitions_are_rejected(self):
        with self.assertRaises(IdentityError):
            self.m.require_step_up()                                  # UNAUTHENTICATED -> STEP_UP

    def test_session_cannot_be_edited_from_outside(self):
        s = self.m.start_guest()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s.role = ROLE_OWNER                                       # type: ignore[misc]
        self.assertEqual(self.m.current().role, ROLE_GUEST)


class GuestDefaultDenyTests(unittest.TestCase):
    def setUp(self):
        self.m = IdentityManager()
        identity.reset_for_tests(self.m)
        self.addCleanup(identity.reset_for_tests, None)

    def test_guest_allowlist_and_everything_else_denied(self):
        self.m.start_guest()
        self.assertTrue(self.m.authorize("weather_report", "SAFE").allowed)
        self.assertFalse(self.m.authorize("weather_report", "SENSITIVE").allowed)
        for tool in ("recall_memory", "personal_memory", "run_command", "files", "browser_control",
                     "jarvis_settings", "self_heal", "mcp", "autonomous_task", "never-heard-of-it"):
            with self.subTest(tool=tool):
                self.assertFalse(self.m.authorize(tool, "SAFE").allowed)

    def test_categories_cover_the_spec(self):
        self.assertEqual(identity.category_for("run_command"), "shell_execution")
        self.assertEqual(identity.category_for("recall_memory"), "owner_memory")
        self.assertEqual(identity.category_for("jarvis_settings"), "settings_write")
        self.assertEqual(identity.category_for("nonsense"), "unknown")

    def test_guard_blocks_guest_before_running_anything(self):
        ran = []
        self.m.start_guest()
        out = security.guard("run_command", {"command": "echo hi"}, lambda: ran.append(1) or "done")
        self.assertEqual(ran, [])
        self.assertIn("Guest Mode", out)
        out = security.guard("recall_memory", {}, lambda: ran.append(1) or "done")
        self.assertEqual(ran, [])
        self.assertIn("Guest Mode", out)

    def test_guard_lets_a_guest_use_an_allowed_tool(self):
        self.m.start_guest()
        with patch.object(security, "audit"):
            out = security.guard("weather_report", {"city": "Colombo"}, lambda: "sunny")
        self.assertEqual(out, "sunny")

    def test_without_guest_mode_guard_behaviour_is_unchanged(self):
        self.assertFalse(self.m.guest_mode_active())
        with patch.object(security, "audit"):
            self.assertEqual(security.guard("weather_report", {}, lambda: "sunny"), "sunny")


class TaskPasswordSeparationTests(unittest.TestCase):
    """Requirement C: a correct task password never changes the user's identity."""

    def setUp(self):
        self.m = IdentityManager()
        identity.reset_for_tests(self.m)
        self.addCleanup(identity.reset_for_tests, None)

    def test_correct_task_password_leaves_the_guest_a_guest(self):
        self.m.start_guest()
        before = self.m.current()
        result = identity.verify_task_credential("bank-app", "hunter2", lambda p: p == "hunter2")
        self.assertTrue(result.ok)
        self.assertEqual(self.m.current(), before)
        self.assertEqual(self.m.current().role, ROLE_GUEST)
        self.assertFalse(self.m.authorize("recall_memory", "SAFE").allowed)
        self.assertFalse(self.m.authorize("run_command", "DANGEROUS").allowed)

    def test_task_result_cannot_be_used_as_owner_proof(self):
        self.m.start_guest()
        result = identity.verify_task_credential("bank-app", "x", lambda p: True)
        self.m.begin_owner_auth()
        with self.assertRaises(IdentityError):
            self.m.complete_owner_auth(result)                        # type: ignore[arg-type]
        self.assertNotEqual(self.m.current().role, ROLE_OWNER)

    def test_task_credential_function_cannot_reach_the_identity_manager(self):
        names = set(identity.verify_task_credential.__code__.co_names)
        for forbidden in ("get_identity_manager", "OwnerProof", "mint_owner_proof", "_manager", "_session"):
            self.assertNotIn(forbidden, names)

    def test_failing_checker_is_a_plain_failure(self):
        def boom(_):
            raise RuntimeError("down")
        self.assertFalse(identity.verify_task_credential("t", "x", boom).ok)

    def test_pin_or_role_strings_from_the_frontend_do_not_elevate(self):
        self.m.start_guest()
        # authorize() takes no role parameter; a caller cannot name one.
        self.assertNotIn("role", inspect.signature(IdentityManager.authorize).parameters)
        self.assertFalse(self.m.authorize("run_command", "DANGEROUS").allowed)


if __name__ == "__main__":
    unittest.main()
