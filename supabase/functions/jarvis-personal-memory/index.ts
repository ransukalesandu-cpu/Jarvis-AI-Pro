import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { isAllowedFactKey, validatePersonalFact } from "./domain.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-jarvis-host-timestamp, x-jarvis-host-nonce",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json" } });

async function getUserId(req: Request, baseUrl: string, anonKey: string): Promise<string | null> {
  const authorization = req.headers.get("Authorization") || "";
  if (!/^Bearer\s+\S+$/.test(authorization)) return null;
  const response = await fetch(baseUrl + "/auth/v1/user", {
    headers: { apikey: anonKey, Authorization: authorization },
  });
  if (!response.ok) return null;
  const user = await response.json().catch(() => null);
  return typeof user?.id === "string" ? user.id : null;
}

async function adminRequest(baseUrl: string, serviceKey: string, path: string, init: RequestInit = {}): Promise<Response> {
  return await fetch(baseUrl + path, {
    ...init,
    headers: {
      apikey: serviceKey,
      Authorization: "Bearer " + serviceKey,
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
}

async function consumeRequest(baseUrl: string, serviceKey: string, userId: string, nonce: string, timestamp: number): Promise<string> {
  const response = await adminRequest(baseUrl, serviceKey, "/rest/v1/rpc/jarvis_consume_cloud_request", {
    method: "POST",
    body: JSON.stringify({ p_user_id: userId, p_nonce: nonce, p_timestamp: timestamp, p_daily_limit: 100 }),
  });
  if (!response.ok) return "error";
  return await response.json();
}

async function memoryConsent(baseUrl: string, serviceKey: string, userId: string): Promise<boolean> {
  const response = await adminRequest(
    baseUrl, serviceKey,
    "/rest/v1/jarvis_personal_memory_settings?user_id=eq." + encodeURIComponent(userId) + "&select=enabled&limit=1",
  );
  if (!response.ok) throw new Error("consent_lookup_failed");
  const rows = await response.json();
  return Array.isArray(rows) && rows.length > 0 && rows[0]?.enabled === true;
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

  let rawBody: Uint8Array;
  try { rawBody = new Uint8Array(await req.arrayBuffer()); }
  catch { return jsonResponse({ error: "invalid_body" }, 400); }
  if (rawBody.length > 12_000) return jsonResponse({ error: "request_too_large" }, 413);

  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(new TextDecoder().decode(rawBody));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("bad_body");
    body = parsed as Record<string, unknown>;
  } catch { return jsonResponse({ error: "invalid_json" }, 400); }

  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || "";
  const timestampHeader = req.headers.get("X-Jarvis-Host-Timestamp") || "";
  if (!/^\d{10}$/.test(timestampHeader) || nonce.length < 16 || nonce.length > 128) {
    return jsonResponse({ error: "request_nonce_required" }, 400);
  }
  const timestamp = Number(timestampHeader);
  if (!Number.isSafeInteger(timestamp) || Math.abs(Date.now() / 1000 - timestamp) > 300) {
    return jsonResponse({ error: "request_timestamp_invalid" }, 400);
  }
  const usage = await consumeRequest(baseUrl, serviceKey, userId, nonce, timestamp);
  if (usage === "replay") return jsonResponse({ error: "replay_detected" }, 409);
  if (usage === "quota") return jsonResponse({ error: "daily_quota_exceeded" }, 429);
  if (usage !== "ok") return jsonResponse({ error: "security_check_failed" }, 503);

  const operation = String(body.operation || "").toLowerCase();
  if (operation === "consent") {
    if (typeof body.enabled !== "boolean") return jsonResponse({ error: "invalid_consent_value" }, 400);
    const response = await adminRequest(
      baseUrl, serviceKey,
      "/rest/v1/jarvis_personal_memory_settings?on_conflict=user_id",
      {
        method: "POST",
        headers: { Prefer: "resolution=merge-duplicates,return=minimal" },
        body: JSON.stringify({ user_id: userId, enabled: body.enabled, updated_at: new Date().toISOString() }),
      },
    );
    if (!response.ok) return jsonResponse({ error: "consent_update_failed" }, 503);
    return jsonResponse({ ok: true, enabled: body.enabled });
  }

  if (!["list", "upsert", "forget", "clear"].includes(operation)) {
    return jsonResponse({ error: "unsupported_operation" }, 400);
  }

  if (operation === "upsert") {
    let enabled = false;
    try { enabled = await memoryConsent(baseUrl, serviceKey, userId); }
    catch { return jsonResponse({ error: "consent_lookup_failed" }, 503); }
    if (!enabled) return jsonResponse({ error: "personal_memory_consent_required" }, 403);

    const fact = validatePersonalFact({
      fact_key: body.fact_key,
      value: body.value,
      evidence_quote: body.evidence_quote,
    });
    if (!fact.ok) return jsonResponse({ error: fact.reason }, 400);
    const response = await adminRequest(
      baseUrl, serviceKey,
      "/rest/v1/jarvis_personal_memories?on_conflict=user_id,fact_key",
      {
        method: "POST",
        headers: { Prefer: "resolution=merge-duplicates,return=representation" },
        body: JSON.stringify({
          user_id: userId,
          fact_key: fact.fact_key,
          value: fact.value,
          evidence_quote: fact.evidence_quote,
          source: "user_stated",
          updated_at: new Date().toISOString(),
        }),
      },
    );
    if (!response.ok) return jsonResponse({ error: "personal_memory_write_failed" }, 503);
    const rows = await response.json().catch(() => []);
    return jsonResponse({ ok: true, memory: Array.isArray(rows) ? rows[0] ?? null : null });
  }

  if (operation === "list") {
    // The local setting alone is not enough: server-side consent must still be active.
    let enabled = false;
    try { enabled = await memoryConsent(baseUrl, serviceKey, userId); }
    catch { return jsonResponse({ error: "consent_lookup_failed" }, 503); }
    if (!enabled) return jsonResponse({ error: "personal_memory_consent_required" }, 403);
    const response = await adminRequest(
      baseUrl, serviceKey,
      "/rest/v1/jarvis_personal_memories?user_id=eq." + encodeURIComponent(userId) +
      "&select=id,fact_key,value,evidence_quote,source,created_at,updated_at&order=updated_at.desc&limit=50",
    );
    if (!response.ok) return jsonResponse({ error: "personal_memory_read_failed" }, 503);
    const rows = await response.json().catch(() => null);
    if (!Array.isArray(rows)) return jsonResponse({ error: "personal_memory_response_invalid" }, 503);
    return jsonResponse({ ok: true, memories: rows });
  }

  if (operation === "clear") {
    const response = await adminRequest(
      baseUrl, serviceKey,
      "/rest/v1/jarvis_personal_memories?user_id=eq." + encodeURIComponent(userId),
      { method: "DELETE", headers: { Prefer: "return=minimal" } },
    );
    if (!response.ok) return jsonResponse({ error: "personal_memory_clear_failed" }, 503);
    return jsonResponse({ ok: true, deleted: true });
  }

  const factKey = body.fact_key;
  if (!isAllowedFactKey(factKey)) return jsonResponse({ error: "invalid_fact_key" }, 400);
  const response = await adminRequest(
    baseUrl, serviceKey,
    "/rest/v1/jarvis_personal_memories?user_id=eq." + encodeURIComponent(userId) +
    "&fact_key=eq." + encodeURIComponent(factKey),
    { method: "DELETE", headers: { Prefer: "return=minimal" } },
  );
  if (!response.ok) return jsonResponse({ error: "personal_memory_delete_failed" }, 503);
  return jsonResponse({ ok: true, deleted: true, fact_key: factKey });
});
