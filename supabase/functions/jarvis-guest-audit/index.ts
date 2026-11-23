import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { isSessionId, validateUpload } from "./domain.ts";

// Guest audit trail sync for JARVIS (Security V2). The desktop app sends only
// allowlisted, minimal events; this function is the only writer of
// public.jarvis_guest_audit_events. Service-role credentials never leave it.

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-jarvis-host-timestamp, x-jarvis-host-nonce",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json" } });

const MAX_BODY_BYTES = 64_000;

async function getUserId(req: Request, baseUrl: string, anonKey: string): Promise<string | null> {
  const authorization = req.headers.get("Authorization") || "";
  if (!/^Bearer\s+\S+$/.test(authorization)) return null;
  const response = await fetch(baseUrl + "/auth/v1/user", { headers: { apikey: anonKey, Authorization: authorization } });
  if (!response.ok) return null;
  const user = await response.json().catch(() => null);
  return typeof user?.id === "string" ? user.id : null;
}

async function adminRequest(baseUrl: string, serviceKey: string, path: string, init: RequestInit = {}): Promise<Response> {
  return await fetch(baseUrl + path, {
    ...init,
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey, "Content-Type": "application/json", ...(init.headers || {}) },
  });
}

async function consumeRequest(baseUrl: string, serviceKey: string, userId: string, nonce: string, timestamp: number): Promise<string> {
  const response = await adminRequest(baseUrl, serviceKey, "/rest/v1/rpc/jarvis_consume_cloud_request", {
    method: "POST",
    body: JSON.stringify({ p_user_id: userId, p_nonce: nonce, p_timestamp: timestamp, p_daily_limit: 500 }),
  });
  if (!response.ok) return "error";
  return await response.json();
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return jsonResponse({ error: "method_not_allowed" }, 405);

  const baseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!baseUrl || !anonKey || !serviceKey) return jsonResponse({ error: "server_not_configured" }, 503);

  const userId = await getUserId(req, baseUrl, anonKey).catch(() => null);
  if (!userId) return jsonResponse({ error: "authentication_required" }, 401);

  const declared = Number(req.headers.get("Content-Length") || "0");
  if (declared > MAX_BODY_BYTES) return jsonResponse({ error: "request_too_large" }, 413);
  const text = await req.text().catch(() => "");
  if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) return jsonResponse({ error: "request_too_large" }, 413);
  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("bad_body");
    body = parsed as Record<string, unknown>;
  } catch { return jsonResponse({ error: "invalid_json" }, 400); }

  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || "";
  const timestampHeader = req.headers.get("X-Jarvis-Host-Timestamp") || "";
  if (!/^\d{10}$/.test(timestampHeader) || nonce.length < 16 || nonce.length > 128) {
    return jsonResponse({ error: "request_nonce_required" }, 400);
  }
  const timestamp = Number(timestampHeader);
  const nowSeconds = Date.now() / 1000;
  if (Math.abs(nowSeconds - timestamp) > 300) return jsonResponse({ error: "request_timestamp_invalid" }, 400);
  const usage = await consumeRequest(baseUrl, serviceKey, userId, nonce, timestamp);
  if (usage === "replay") return jsonResponse({ error: "replay_detected" }, 409);
  if (usage === "quota") return jsonResponse({ error: "daily_quota_exceeded" }, 429);
  if (usage !== "ok") return jsonResponse({ error: "security_check_failed" }, 503);

  const operation = String(body.operation || "");

  if (operation === "guest_audit_upload") {
    const rows = validateUpload(body.events, nowSeconds);
    if (!rows) return jsonResponse({ error: "invalid_events" }, 400);
    const response = await adminRequest(baseUrl, serviceKey,
      "/rest/v1/jarvis_guest_audit_events?on_conflict=user_id,event_id", {
        method: "POST",
        headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
        body: JSON.stringify(rows.map((r) => ({ ...r, user_id: userId }))),
      });
    if (!response.ok) return jsonResponse({ error: "guest_audit_save_failed" }, 503);
    return jsonResponse({ ok: true, stored: rows.map((r) => r.event_id) });
  }

  if (operation === "guest_audit_delete_session") {
    if (!isSessionId(body.guest_session_id)) return jsonResponse({ error: "invalid_session_id" }, 400);
    const response = await adminRequest(baseUrl, serviceKey,
      "/rest/v1/jarvis_guest_audit_events?user_id=eq." + encodeURIComponent(userId) +
      "&guest_session_id=eq." + encodeURIComponent(body.guest_session_id),
      { method: "DELETE", headers: { Prefer: "return=minimal" } });
    if (!response.ok) return jsonResponse({ error: "guest_audit_delete_failed" }, 503);
    return jsonResponse({ ok: true, deleted: true });
  }

  return jsonResponse({ error: "unknown_operation" }, 400);
});
