import { assertEquals } from "jsr:@std/assert";
import { MAX_EVENTS_PER_UPLOAD, RETENTION_SECONDS, validateEvent, validateUpload } from "./domain.ts";

const NOW = 1_795_000_000;
const ok = {
  event_id: "a1b2c3d4e5f60718", guest_session_id: "s_abc123", event_type: "restricted_action_denied",
  action_category: "shell_execution", outcome: "denied", ts: NOW - 60,
  safe_metadata: { tool: "run_command", tier: "DANGEROUS", reason: "guest_default_deny" },
};

Deno.test("valid event becomes a row with a 7-day expiry", () => {
  const row = validateEvent(ok, NOW)!;
  assertEquals(row.event_type, "restricted_action_denied");
  assertEquals(Date.parse(row.expires_at) - Date.parse(row.created_at), RETENTION_SECONDS * 1000);
});

Deno.test("free text and unknown values are rejected", () => {
  assertEquals(validateEvent({ ...ok, note: "said a password" }, NOW), null);
  assertEquals(validateEvent({ ...ok, safe_metadata: { command: "rm -rf" } }, NOW), null);
  assertEquals(validateEvent({ ...ok, safe_metadata: { tool: "Run Command!" } }, NOW), null);
  assertEquals(validateEvent({ ...ok, event_type: "keystroke" }, NOW), null);
  assertEquals(validateEvent({ ...ok, outcome: "maybe" }, NOW), null);
  assertEquals(validateEvent({ ...ok, event_id: "../x" }, NOW), null);
});

Deno.test("future and expired timestamps are rejected", () => {
  assertEquals(validateEvent({ ...ok, ts: NOW + 3600 }, NOW), null);
  assertEquals(validateEvent({ ...ok, ts: NOW - RETENTION_SECONDS - 1 }, NOW), null);
});

Deno.test("uploads are all-or-nothing, bounded and duplicate-free", () => {
  assertEquals(validateUpload([ok, { ...ok, event_id: "ffffffffffffffff" }], NOW)?.length, 2);
  assertEquals(validateUpload([ok, ok], NOW), null);
  assertEquals(validateUpload([ok, { ...ok, outcome: "x" }], NOW), null);
  assertEquals(validateUpload([], NOW), null);
  assertEquals(validateUpload(Array(MAX_EVENTS_PER_UPLOAD + 1).fill(ok), NOW), null);
});
