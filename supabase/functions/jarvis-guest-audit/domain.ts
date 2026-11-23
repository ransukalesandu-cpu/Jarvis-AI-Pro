// Validation for Guest audit events uploaded by the JARVIS desktop app (Security V2).
// Mirrors jarvis/core/guest_audit.py and the CHECK constraints of
// supabase/migrations/202611050001_security_v2_guest_audit.sql. Anything not on an
// allowlist is rejected, so no free text can reach the server.

export const RETENTION_SECONDS = 7 * 24 * 3600;
export const MAX_EVENTS_PER_UPLOAD = 100;

export const EVENT_TYPES = new Set([
  "guest_session_started", "guest_session_ended", "guest_notice_shown",
  "restricted_action_attempted", "restricted_action_denied",
  "authentication_failed", "security_policy_blocked_action",
]);
export const OUTCOMES = new Set(["allowed", "denied", "info"]);
export const CATEGORIES = new Set([
  "none", "general_chat", "owner_memory", "personal_data", "secret_access", "settings_read", "settings_write",
  "voice_identity", "owner_management", "security_management", "computer_control", "file_management",
  "shell_execution", "browser_automation", "plugin_execution", "task_automation", "guest_history", "unknown",
]);
export const REASONS = new Set(["guest_default_deny", "not_signed_in", "wrong_credential", "locked", "session_timeout", "policy"]);
export const TIERS = new Set(["SAFE", "SENSITIVE", "DANGEROUS"]);

const EVENT_ID_RE = /^[a-f0-9]{8,40}$/;
const SESSION_ID_RE = /^[A-Za-z0-9_-]{1,32}$/;
const TOOL_RE = /^[a-z0-9_]{1,40}$/;

export interface GuestAuditRow {
  event_id: string;
  guest_session_id: string;
  event_type: string;
  action_category: string;
  outcome: string;
  safe_metadata: Record<string, string>;
  created_at: string;
  expires_at: string;
}

export function isSessionId(value: unknown): value is string {
  return typeof value === "string" && SESSION_ID_RE.test(value);
}

function cleanMetadata(raw: unknown): Record<string, string> | null {
  if (raw === undefined || raw === null) return {};
  if (typeof raw !== "object" || Array.isArray(raw)) return null;
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value !== "string") return null;
    if (key === "tool" && (TOOL_RE.test(value) || value === "other")) out.tool = value;
    else if (key === "tier" && TIERS.has(value)) out.tier = value;
    else if (key === "reason" && REASONS.has(value)) out.reason = value;
    else return null;
  }
  return out;
}

/** Validate one event; returns the DB row or null. ``nowSeconds`` is injectable for tests. */
export function validateEvent(raw: unknown, nowSeconds: number): GuestAuditRow | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const e = raw as Record<string, unknown>;
  const allowed = new Set(["event_id", "guest_session_id", "event_type", "action_category", "outcome", "ts", "safe_metadata"]);
  if (Object.keys(e).some((k) => !allowed.has(k))) return null;
  if (typeof e.event_id !== "string" || !EVENT_ID_RE.test(e.event_id)) return null;
  if (!isSessionId(e.guest_session_id)) return null;
  if (typeof e.event_type !== "string" || !EVENT_TYPES.has(e.event_type)) return null;
  if (typeof e.action_category !== "string" || !CATEGORIES.has(e.action_category)) return null;
  if (typeof e.outcome !== "string" || !OUTCOMES.has(e.outcome)) return null;
  if (typeof e.ts !== "number" || !Number.isFinite(e.ts)) return null;
  // Not from the future (5 min clock skew) and not already expired.
  if (e.ts > nowSeconds + 300 || e.ts <= nowSeconds - RETENTION_SECONDS) return null;
  const metadata = cleanMetadata(e.safe_metadata);
  if (metadata === null) return null;
  const created = Math.min(e.ts, nowSeconds);
  return {
    event_id: e.event_id,
    guest_session_id: e.guest_session_id,
    event_type: e.event_type,
    action_category: e.action_category,
    outcome: e.outcome,
    safe_metadata: metadata,
    created_at: new Date(created * 1000).toISOString(),
    expires_at: new Date((created + RETENTION_SECONDS) * 1000).toISOString(),
  };
}

/** Validate a whole upload: all-or-nothing, so a tampered batch is never partly stored. */
export function validateUpload(events: unknown, nowSeconds: number): GuestAuditRow[] | null {
  if (!Array.isArray(events) || events.length === 0 || events.length > MAX_EVENTS_PER_UPLOAD) return null;
  const rows: GuestAuditRow[] = [];
  const seen = new Set<string>();
  for (const raw of events) {
    const row = validateEvent(raw, nowSeconds);
    if (!row || seen.has(row.event_id)) return null;
    seen.add(row.event_id);
    rows.push(row);
  }
  return rows;
}
