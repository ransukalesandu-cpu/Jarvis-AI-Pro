"""Security V2 Phase 2: multiple independent owners, admin rules, lockout, recovery, voice."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher

from jarvis.core import identity, owner_registry as reg_mod
from jarvis.core.identity import IdentityManager, ROLE_GUEST, ROLE_OWNER
from jarvis.core.owner_registry import OwnerError, OwnerRegistry
from jarvis.core.owner_store import OwnerStore

FAST = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = [10_000.0]
        self.store = OwnerStore(Path(self.tmp.name) / "owner.db")
        self.removed: list[str] = []
        self.enrolled: dict[str, object] = {}
        self.voices: dict[str, str] = {}          # role -> the "voice" it accepts
        self.reg = OwnerRegistry(
            self.store, hasher=FAST, clock=lambda: self.now[0],
            voice_verify=lambda audio, role: (self.voices.get(role) == audio, 0.9 if self.voices.get(role) == audio else 0.0),
            voice_enroll=lambda audio, role: self.voices.__setitem__(role, audio),
            voice_remove=lambda role: (self.removed.append(role), self.voices.pop(role, None)))
        self.mgr = IdentityManager(clock=lambda: self.now[0])
        self.audits: list[tuple] = []
        patcher = patch("jarvis.core.security.audit", lambda *a, **k: self.audits.append(a))
        patcher.start()
        self.addCleanup(patcher.stop)

    def boot(self):
        owner, code = self.reg.bootstrap_first_owner("Lesandu", "first-pin")
        return owner, code

    def sign_in(self, pin, owner_id=""):
        proof = self.reg.authenticate_pin(pin, owner_id)
        self.mgr.end_session()
        return self.reg.login(self.mgr, proof)

    def admin_ready(self, pin="first-pin"):
        s = self.sign_in(pin)
        self.reg.confirm_step_up(self.mgr, pin)
        return s


class BootstrapAndIdentityTests(Base):
    def test_first_owner_is_primary_admin_and_only_once(self):
        owner, code = self.boot()
        self.assertTrue(owner["is_admin"])
        self.assertGreaterEqual(len(code), 16)
        with self.assertRaises(OwnerError):
            self.reg.bootstrap_first_owner("Intruder", "other-pin")
        self.assertEqual(len(self.reg.list_owners()), 1)

    def test_secret_and_name_validation(self):
        for name, pin in (("", "1234"), ("x" * 41, "1234"), ("ok", "123"), ("ok", "p" * 65)):
            with self.assertRaises(OwnerError, msg=(name, pin)):
                self.reg.bootstrap_first_owner(name, pin)

    def test_nothing_secret_is_stored_or_listed(self):
        owner, code = self.boot()
        raw = self.store.path.read_bytes()
        self.assertNotIn(b"first-pin", raw)
        self.assertNotIn(code.encode(), raw)
        self.assertNotIn("pin_hash", repr(self.reg.list_owners()))

    def test_two_owners_have_separate_identities_and_sessions(self):
        a, _ = self.boot()
        self.admin_ready()
        b = self.reg.add_owner(self.mgr, "Sister", "second-pin")
        self.assertNotEqual(a["owner_id"], b["owner_id"])
        sa = self.sign_in("first-pin")
        sb = self.sign_in("second-pin")
        self.assertEqual((sa.role, sa.owner_id), (ROLE_OWNER, a["owner_id"]))
        self.assertEqual((sb.role, sb.owner_id), (ROLE_OWNER, b["owner_id"]))
        self.assertNotEqual(sa.session_id, sb.session_id)
        self.assertIsNone(self.reg.authenticate_pin("second-pin", a["owner_id"]))   # b's PIN is not a's
        self.assertFalse(b["is_admin"])

    def test_wrong_pin_makes_no_session(self):
        self.boot()
        self.assertIsNone(self.reg.authenticate_pin("nope-nope"))
        with self.assertRaises(OwnerError):
            self.reg.login(self.mgr, None)
        self.assertNotEqual(self.mgr.current().role, ROLE_OWNER)


class AdministrationTests(Base):
    def test_guest_and_plain_owner_cannot_manage_owners(self):
        self.boot()
        self.mgr.start_guest()
        with self.assertRaises(OwnerError):
            self.reg.add_owner(self.mgr, "Evil", "evil-pin")                # Guest
        self.admin_ready()
        self.reg.add_owner(self.mgr, "Sister", "second-pin")
        self.sign_in("second-pin")
        self.reg.confirm_step_up(self.mgr, "second-pin")
        with self.assertRaises(OwnerError):
            self.reg.add_owner(self.mgr, "Evil", "evil-pin")                # owner, not admin
        self.assertEqual(len(self.reg.list_owners()), 2)

    def test_management_needs_a_fresh_step_up(self):
        self.boot()
        self.sign_in("first-pin")
        with self.assertRaises(OwnerError):
            self.reg.add_owner(self.mgr, "B", "second-pin")
        self.reg.confirm_step_up(self.mgr, "first-pin")
        self.reg.add_owner(self.mgr, "B", "second-pin")
        self.now[0] += identity.STEP_UP_WINDOW_SECONDS + 1
        with self.assertRaises(OwnerError):
            self.reg.add_owner(self.mgr, "C", "third-pin")

    def test_last_admin_cannot_be_revoked_or_demoted(self):
        a, _ = self.boot()
        self.admin_ready()
        with self.assertRaises(OwnerError):
            self.reg.revoke_owner(self.mgr, a["owner_id"])
        with self.assertRaises(OwnerError):
            self.reg.set_admin(self.mgr, a["owner_id"], False)
        b = self.reg.add_owner(self.mgr, "B", "second-pin", admin=True)
        self.reg.set_admin(self.mgr, a["owner_id"], False)                 # fine: b is admin too
        self.sign_in("first-pin")
        self.reg.confirm_step_up(self.mgr, "first-pin")
        with self.assertRaises(OwnerError) as ctx:
            self.reg.revoke_owner(self.mgr, b["owner_id"])                 # a is no longer admin
        self.assertIn("administrator", str(ctx.exception))

    def test_revocation_ends_sessions_blocks_login_and_removes_voice(self):
        a, _ = self.boot()
        self.admin_ready()
        b = self.reg.add_owner(self.mgr, "B", "second-pin")
        self.reg.enroll_voice(b["owner_id"], "b-voice")
        other = IdentityManager(clock=lambda: self.now[0])
        other.begin_owner_auth()
        other.complete_owner_auth(self.reg.authenticate_pin("second-pin", b["owner_id"]))
        self.assertEqual(other.current().role, ROLE_OWNER)
        self.reg.revoke_owner(self.mgr, b["owner_id"])
        other.revoke_owner(b["owner_id"])
        self.assertEqual(other.current().state, identity.REVOKED)
        self.assertIsNone(self.reg.authenticate_pin("second-pin", b["owner_id"]))
        self.assertIsNone(self.reg.authenticate_voice("b-voice", b["owner_id"]))
        self.assertIn(f"owner-{b['owner_id'][:8]}", self.removed)
        self.assertEqual([o["status"] for o in self.reg.list_owners()], ["active", "revoked"])
        self.assertEqual(self.mgr.current().owner_id, a["owner_id"])      # the admin is still signed in


class LockoutTests(Base):
    def test_three_wrong_pins_lock_that_owner_with_growing_delay(self):
        a, _ = self.boot()
        oid = a["owner_id"]
        for _ in range(3):
            self.assertIsNone(self.reg.authenticate_pin("wrong-pin", oid))
        self.assertGreater(self.reg.lock_seconds_remaining(oid), 0)
        self.assertIsNone(self.reg.authenticate_pin("first-pin", oid))      # right PIN refused while locked
        self.now[0] += reg_mod.BASE_LOCK_SECONDS + 1
        self.assertIsNone(self.reg.authenticate_pin("wrong-pin", oid))      # 4th failure -> longer lock
        self.assertGreater(self.reg.lock_seconds_remaining(oid), reg_mod.BASE_LOCK_SECONDS)
        self.now[0] += reg_mod.MAX_LOCK_SECONDS + 1
        self.assertIsNotNone(self.reg.authenticate_pin("first-pin", oid))
        self.assertEqual(self.reg.lock_seconds_remaining(oid), 0)

    def test_one_owner_locked_does_not_lock_the_other(self):
        a, _ = self.boot()
        self.admin_ready()
        b = self.reg.add_owner(self.mgr, "B", "second-pin")
        for _ in range(3):
            self.reg.authenticate_pin("wrong-pin", a["owner_id"])
        self.assertIsNotNone(self.reg.authenticate_pin("second-pin", b["owner_id"]))


class VoiceTests(Base):
    def test_each_owner_has_their_own_voice_profile(self):
        a, _ = self.boot()
        self.admin_ready()
        b = self.reg.add_owner(self.mgr, "B", "second-pin")
        self.reg.enroll_voice(a["owner_id"], "voice-a")
        self.reg.enroll_voice(b["owner_id"], "voice-b")
        self.assertNotEqual(f"owner-{a['owner_id'][:8]}", f"owner-{b['owner_id'][:8]}")
        pa = self.reg.authenticate_voice("voice-a")
        pb = self.reg.authenticate_voice("voice-b")
        self.assertEqual((pa.owner_id, pa.method), (a["owner_id"], "voice"))
        self.assertEqual(pb.owner_id, b["owner_id"])
        self.assertIsNone(self.reg.authenticate_voice("a stranger"))
        self.assertIsNone(self.reg.authenticate_voice("voice-a", b["owner_id"]))   # a's voice is not b's

    def test_replacing_a_voice_profile_invalidates_the_old_voice(self):
        a, _ = self.boot()
        self.reg.enroll_voice(a["owner_id"], "old-voice")
        self.reg.enroll_voice(a["owner_id"], "new-voice")
        self.assertIsNone(self.reg.authenticate_voice("old-voice"))
        self.assertIsNotNone(self.reg.authenticate_voice("new-voice"))

    def test_voice_fails_closed_when_voice_id_is_off(self):
        reg = OwnerRegistry(self.store, hasher=FAST, clock=lambda: self.now[0])
        reg.bootstrap_first_owner("A", "first-pin")
        with patch("jarvis.core.voice_id.is_enabled", return_value=False):
            self.assertIsNone(reg.authenticate_voice("anything"))             # never "everyone is owner"


class RecoveryTests(Base):
    def test_recovery_code_restores_admin_and_rotates(self):
        a, code = self.boot()
        for _ in range(3):
            self.reg.authenticate_pin("wrong-pin", a["owner_id"])
        owner, new_code = self.reg.recover_admin(code, "brand-new-pin")
        self.assertNotEqual(code, new_code)
        self.assertEqual(self.reg.lock_seconds_remaining(a["owner_id"]), 0)
        self.assertIsNotNone(self.reg.authenticate_pin("brand-new-pin", a["owner_id"]))
        self.assertIsNone(self.reg.authenticate_pin("first-pin", a["owner_id"]))
        with self.assertRaises(OwnerError):
            self.reg.recover_admin(code, "x-another")                        # old code is spent

    def test_wrong_codes_are_limited(self):
        self.boot()
        for _ in range(reg_mod.MAX_RECOVERY_ATTEMPTS):
            with self.assertRaises(OwnerError):
                self.reg.recover_admin("wrong", "whatever-pin")
        with self.assertRaises(OwnerError) as ctx:
            self.reg.recover_admin("wrong", "whatever-pin")
        self.assertIn("too many", str(ctx.exception))

    def test_recovery_cannot_make_a_non_admin_an_admin(self):
        a, code = self.boot()
        self.admin_ready()
        b = self.reg.add_owner(self.mgr, "B", "second-pin")
        with self.assertRaises(OwnerError):
            self.reg.recover_admin(code, "new-pin-here", owner_id=b["owner_id"])


class AuditHygieneTests(Base):
    def test_audit_records_never_contain_secrets(self):
        a, code = self.boot()
        self.admin_ready()
        self.reg.add_owner(self.mgr, "B", "second-pin")
        self.reg.authenticate_pin("wrong-pin", a["owner_id"])
        self.reg.recover_admin(code, "brand-new-pin")
        blob = repr(self.audits)
        for secret in ("first-pin", "second-pin", "wrong-pin", "brand-new-pin", code):
            self.assertNotIn(secret, blob)
        self.assertGreater(len(self.audits), 3)


class GuestCannotBecomeOwnerTests(Base):
    def test_guest_cannot_enroll_or_log_in_without_a_credential(self):
        self.boot()
        self.mgr.start_guest()
        with self.assertRaises(OwnerError):
            self.reg.bootstrap_first_owner("Guest", "guest-pin")
        with self.assertRaises(OwnerError):
            self.reg.add_owner(self.mgr, "Guest", "guest-pin")
        with self.assertRaises(OwnerError):
            self.reg.login(self.mgr, self.reg.authenticate_pin("guessing"))
        self.assertEqual(self.mgr.current().role, ROLE_GUEST)


if __name__ == "__main__":
    unittest.main()


class CliTests(Base):
    """scripts/security_owners.py end to end (PINs typed at the console, never spoken)."""

    def run_cli(self, argv, *answers):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "security_owners_cli", Path(__file__).resolve().parents[2] / "scripts" / "security_owners.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        feed = iter(answers)
        lines: list[str] = []
        code = mod.run(argv, registry=self.reg, ask=lambda prompt: next(feed), out=lines.append,
                       record=lambda: "cli-voice")
        return code, "\n".join(lines)

    def test_init_add_list_revoke_flow(self):
        code, text = self.run_cli(["init", "--name", "Lesandu"], "first-pin", "first-pin")
        self.assertEqual(code, 0)
        self.assertIn("RECOVERY CODE", text)
        code, _ = self.run_cli(["init", "--name", "Again"], "x-pin-1", "x-pin-1")
        self.assertEqual(code, 2)                                           # second init refused
        code, text = self.run_cli(["add", "--name", "Sister"], "first-pin", "first-pin", "second-pin", "second-pin")
        self.assertEqual(code, 0, text)
        code, listing = self.run_cli(["list"])
        self.assertIn("Sister", listing)
        sister = next(o for o in self.reg.list_owners() if o["display_name"] == "Sister")
        code, text = self.run_cli(["revoke", sister["owner_id"]], "first-pin", "first-pin")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.reg.list_owners()[1]["status"], "revoked")

    def test_wrong_pin_stops_admin_commands(self):
        self.boot()
        code, text = self.run_cli(["add", "--name", "X"], "bad-pin-1")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.reg.list_owners()), 1)

    def test_enroll_voice_and_change_pin(self):
        a, _ = self.boot()
        code, _ = self.run_cli(["enroll-voice", a["owner_id"]], "first-pin")
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.reg.authenticate_voice("cli-voice"))
        code, _ = self.run_cli(["change-pin", a["owner_id"]], "first-pin", "newer-pin", "newer-pin")
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.reg.authenticate_pin("newer-pin", a["owner_id"]))
