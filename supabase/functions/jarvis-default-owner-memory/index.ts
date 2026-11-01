import "jsr:@supabase/functions-js/edge-runtime.d.ts";
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-jarvis-host-timestamp, x-jarvis-host-nonce",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json", "Cache-Control": "no-store" } });

async function getUserId(req: Request, baseUrl: string, anonKey: string): Promise<string | null> {
  const authorization = req.headers.get("Authorization") || "";
  if (!/^Bearer\s+\S+$/.test(authorization)) return null;
  const response = await fetch(baseUrl + "/auth/v1/user", { headers: { apikey: anonKey, Authorization: authorization } });
  if (!response.ok) return null;
  const user = await response.json().catch(() => null);
  return typeof user?.id === "string" ? user.id : null;
}
async function adminRequest(baseUrl: string, serviceKey: string, path: string, init: RequestInit = {}): Promise<Response> {
  return await fetch(baseUrl + path, { ...init, headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey, "Content-Type": "application/json", ...(init.headers || {}) } });
}
async function consumeRequest(baseUrl: string, serviceKey: string, userId: string, nonce: string, timestamp: number): Promise<string> {
  const response = await adminRequest(baseUrl, serviceKey, "/rest/v1/rpc/jarvis_consume_cloud_request", { method: "POST", body: JSON.stringify({ p_user_id: userId, p_nonce: nonce, p_timestamp: timestamp, p_daily_limit: 100 }) });
  if (!response.ok) return "error";
  return await response.json();
}
async function verifyEnrolledDevice(
  rawBody: Uint8Array,
  userId: string,
  baseUrl: string,
  serviceKey: string,
  timestamp: string,
  nonce: string,
  keyHeader: string,
  signatureHeader: string,
): Promise<boolean> {
  if (!keyHeader || !signatureHeader) return false;
  let publicKey: Uint8Array;
  let signature: Uint8Array;
  try {
    publicKey = Uint8Array.from(atob(keyHeader), (ch) => ch.charCodeAt(0));
    signature = Uint8Array.from(atob(signatureHeader), (ch) => ch.charCodeAt(0));
  } catch { return false; }
  if (publicKey.length !== 32 || signature.length !== 64) return false;

  const deviceResponse = await adminRequest(
    baseUrl, serviceKey,
    "/rest/v1/jarvis_host_devices?user_id=eq." + encodeURIComponent(userId) +
      "&select=public_key_b64,revoked_at&limit=1",
  );
  if (!deviceResponse.ok) return false;
  const devices = await deviceResponse.json().catch(() => null);
  if (!Array.isArray(devices) || devices.length !== 1) return false;
  if (devices[0]?.revoked_at || devices[0]?.public_key_b64 !== keyHeader) return false;

  const digest = await crypto.subtle.digest("SHA-256", rawBody);
  const digestHex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  const message = new TextEncoder().encode(`JARVIS-HOST-V1\\n${timestamp}\\n${nonce}\\n${digestHex}`);
  try {
    const imported = await crypto.subtle.importKey("raw", publicKey, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify({ name: "Ed25519" }, imported, signature, message);
  } catch { return false; }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return jsonResponse({ error: "method_not_allowed" }, 405);
  const baseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!baseUrl || !anonKey || !serviceKey) return jsonResponse({ error: "server_not_configured" }, 503);
  // Owner and Guest modes use a valid per-installation anonymous Auth session.
  // Local owner signing is intentionally not required for this read-only profile.
  const userId = await getUserId(req, baseUrl, anonKey).catch(() => null);
  if (!userId) return jsonResponse({ error: "authentication_required" }, 401);
  const rawBody = new Uint8Array(await req.arrayBuffer());
  if (rawBody.length > 1024) return jsonResponse({ error: "request_too_large" }, 413);
  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || "";
  const timestampHeader = req.headers.get("X-Jarvis-Host-Timestamp") || "";
  if (!/^\\d{10}$/.test(timestampHeader) || nonce.length < 16 || nonce.length > 128) return jsonResponse({ error: "request_nonce_required" }, 400);
  const timestamp = Number(timestampHeader);
  if (!Number.isSafeInteger(timestamp) || Math.abs(Date.now() / 1000 - timestamp) > 300) return jsonResponse({ error: "request_timestamp_invalid" }, 400);

  // Shared private profile reads require the already-enrolled device key.
  // This endpoint deliberately never enrolls devices as a side effect.
  const deviceVerified = await verifyEnrolledDevice(
    rawBody, userId, baseUrl, serviceKey, timestampHeader, nonce,
    req.headers.get("X-Jarvis-Host-Key") || "",
    req.headers.get("X-Jarvis-Host-Signature") || "",
  ).catch(() => false);
  if (!deviceVerified) return jsonResponse({ error: "enrolled_device_required" }, 403);

  const usage = await consumeRequest(baseUrl, serviceKey, userId, nonce, timestamp);
  if (usage === "replay") return jsonResponse({ error: "replay_detected" }, 409);
  if (usage === "quota") return jsonResponse({ error: "daily_quota_exceeded" }, 429);
  if (usage !== "ok") return jsonResponse({ error: "security_check_failed" }, 503);
  const response = await adminRequest(baseUrl, serviceKey, "/rest/v1/rpc/jarvis_get_default_owner_memory", { method: "POST", body: "{}" });
  if (!response.ok) return jsonResponse({ error: "default_memory_unavailable" }, 503);
  const profile = await response.json().catch(() => null);
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) return jsonResponse({ error: "default_memory_not_found" }, 404);
  return jsonResponse({ ok: true, profile });
});
