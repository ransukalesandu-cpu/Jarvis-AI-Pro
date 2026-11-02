import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-jarvis-host-key, x-jarvis-host-timestamp, x-jarvis-host-nonce, x-jarvis-host-signature",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json", "Cache-Control": "no-store" },
  });

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}
async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

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
async function getEnrolledDevice(baseUrl: string, serviceKey: string, userId: string) {
  const response = await adminRequest(
    baseUrl,
    serviceKey,
    "/rest/v1/jarvis_host_devices?user_id=eq." + encodeURIComponent(userId) + "&select=public_key_b64,revoked_at",
  );
  if (!response.ok) throw new Error("device_lookup_failed");
  const rows = await response.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}
async function verifyEnrolledHost(
  req: Request,
  rawBody: Uint8Array,
  userId: string,
  baseUrl: string,
  serviceKey: string,
): Promise<boolean> {
  const keyHeader = req.headers.get("X-Jarvis-Host-Key") || "";
  const timestamp = req.headers.get("X-Jarvis-Host-Timestamp") || "";
  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || "";
  const signatureHeader = req.headers.get("X-Jarvis-Host-Signature") || "";
  if (!keyHeader || !signatureHeader || !/^\d{10}$/.test(timestamp) || nonce.length < 16 || nonce.length > 128) {
    return false;
  }
  const timestampNumber = Number(timestamp);
  if (!Number.isSafeInteger(timestampNumber) || Math.abs(Date.now() / 1000 - timestampNumber) > 300) return false;

  let suppliedKey: Uint8Array;
  let signature: Uint8Array;
  try {
    suppliedKey = decodeBase64(keyHeader);
    signature = decodeBase64(signatureHeader);
    if (suppliedKey.length !== 32 || signature.length !== 64) return false;
  } catch {
    return false;
  }

  const digest = await sha256Hex(rawBody);
  const message = new TextEncoder().encode("JARVIS-HOST-V1\n" + timestamp + "\n" + nonce + "\n" + digest);
  let verified = false;
  try {
    const cryptoKey = await crypto.subtle.importKey("raw", suppliedKey, { name: "Ed25519" }, false, ["verify"]);
    verified = await crypto.subtle.verify({ name: "Ed25519" }, cryptoKey, signature, message);
  } catch {
    return false;
  }
  if (!verified) return false;

  let device;
  try {
    device = await getEnrolledDevice(baseUrl, serviceKey, userId);
  } catch {
    return false;
  }
  return Boolean(device && !device.revoked_at && device.public_key_b64 === keyHeader);
}
async function consumeRequest(baseUrl: string, serviceKey: string, userId: string, nonce: string, timestamp: number): Promise<string> {
  const response = await adminRequest(
    baseUrl,
    serviceKey,
    "/rest/v1/rpc/jarvis_consume_cloud_request",
    {
      method: "POST",
      body: JSON.stringify({ p_user_id: userId, p_nonce: nonce, p_timestamp: timestamp, p_daily_limit: 100 }),
    },
  );
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

  let rawBody: Uint8Array;
  try {
    rawBody = new Uint8Array(await req.arrayBuffer());
  } catch {
    return jsonResponse({ error: "invalid_body" }, 400);
  }
  if (rawBody.length > 1024) return jsonResponse({ error: "request_too_large" }, 413);
  try {
    const parsed = JSON.parse(new TextDecoder().decode(rawBody));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("invalid_body");
  } catch {
    return jsonResponse({ error: "invalid_json" }, 400);
  }

  // A Supabase anonymous JWT alone is not a device identity. Only an already
  // enrolled installation can read the fixed owner profile, in Owner or Guest mode.
  const hostVerified = await verifyEnrolledHost(req, rawBody, userId, baseUrl, serviceKey).catch(() => false);
  if (!hostVerified) return jsonResponse({ error: "enrolled_host_required" }, 403);

  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || "";
  const timestampHeader = req.headers.get("X-Jarvis-Host-Timestamp") || "";
  const timestamp = Number(timestampHeader);
  const usage = await consumeRequest(baseUrl, serviceKey, userId, nonce, timestamp);
  if (usage === "replay") return jsonResponse({ error: "replay_detected" }, 409);
  if (usage === "quota") return jsonResponse({ error: "daily_quota_exceeded" }, 429);
  if (usage !== "ok") return jsonResponse({ error: "security_check_failed" }, 503);

  const response = await adminRequest(
    baseUrl,
    serviceKey,
    "/rest/v1/rpc/jarvis_get_default_owner_memory",
    { method: "POST", body: "{}" },
  );
  if (!response.ok) return jsonResponse({ error: "default_memory_unavailable" }, 503);
  const profile = await response.json().catch(() => null);
  if (!profile || typeof profile !== "object" || Array.isArray(profile)) {
    return jsonResponse({ error: "default_memory_not_found" }, 404);
  }
  return jsonResponse({ ok: true, profile });
});
