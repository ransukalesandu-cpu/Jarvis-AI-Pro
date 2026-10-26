import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-jarvis-host-key, x-jarvis-host-timestamp, x-jarvis-host-nonce, x-jarvis-host-signature, x-jarvis-host-enrollment",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
type Provider = "gemini" | "openai" | "groq" | "anthropic";
const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...corsHeaders, "Content-Type": "application/json" } });

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}
function encodeBase64Url(value: string): string {
  return value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
}
async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
async function getUserId(req: Request, baseUrl: string, anonKey: string): Promise<string | null> {
  const authorization = req.headers.get("Authorization") || "";
  if (!/^Bearer\s+\S+$/.test(authorization)) return null;
  // Validate the JWT against Supabase Auth rather than trusting decoded client claims.
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
async function getDevice(baseUrl: string, serviceKey: string, userId: string) {
  const response = await adminRequest(baseUrl, serviceKey,
    "/rest/v1/jarvis_host_devices?user_id=eq." + encodeURIComponent(userId) + "&select=public_key_b64,revoked_at");
  if (!response.ok) throw new Error("device_lookup_failed");
  const rows = await response.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}
async function verifyHostSignature(req: Request, rawBody: Uint8Array, userId: string, baseUrl: string, serviceKey: string): Promise<"host" | "normal" | "invalid"> {
  const keyHeader = req.headers.get("X-Jarvis-Host-Key");
  const timestamp = req.headers.get("X-Jarvis-Host-Timestamp");
  const nonce = req.headers.get("X-Jarvis-Host-Nonce");
  const signatureHeader = req.headers.get("X-Jarvis-Host-Signature");
  const enrollment = req.headers.get("X-Jarvis-Host-Enrollment");
  const hasAnyHostHeader = Boolean(keyHeader || timestamp || nonce || signatureHeader || enrollment);
  if (!hasAnyHostHeader) return "normal";
  if (!keyHeader || !timestamp || !nonce || !signatureHeader ||
      !/^\d{10}$/.test(timestamp) || nonce.length < 16 || nonce.length > 128) return "invalid";
  const timestampNumber = Number(timestamp);
  if (!Number.isSafeInteger(timestampNumber) || Math.abs(Date.now() / 1000 - timestampNumber) > 300) return "invalid";

  let suppliedKey: Uint8Array, signature: Uint8Array;
  try {
    suppliedKey = decodeBase64(keyHeader);
    signature = decodeBase64(signatureHeader);
    if (suppliedKey.length !== 32 || signature.length !== 64) return "invalid";
  } catch { return "invalid"; }

  const digest = await sha256Hex(rawBody);
  const message = new TextEncoder().encode(`JARVIS-HOST-V1\n${timestamp}\n${nonce}\n${digest}`);
  let verified = false;
  try {
    const cryptoKey = await crypto.subtle.importKey("raw", suppliedKey, { name: "Ed25519" }, false, ["verify"]);
    verified = await crypto.subtle.verify({ name: "Ed25519" }, cryptoKey, signature, message);
  } catch { return "invalid"; }
  if (!verified) return "invalid";

  const suppliedKeyB64 = keyHeader;
  let device;
  try { device = await getDevice(baseUrl, serviceKey, userId); }
  catch { return "invalid"; }
  if (!device) {
    const enrollmentToken = Deno.env.get("JARVIS_HOST_ENROLLMENT_TOKEN");
    if (!enrollmentToken || !enrollment || enrollment !== enrollmentToken) return "invalid";
    const insert = await adminRequest(baseUrl, serviceKey, "/rest/v1/jarvis_host_devices", {
      method: "POST",
      headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
      body: JSON.stringify({ user_id: userId, public_key_b64: suppliedKeyB64 }),
    });
    if (!insert.ok) return "invalid";
    try { device = await getDevice(baseUrl, serviceKey, userId); }
    catch { return "invalid"; }
  }
  if (!device || device.revoked_at || device.public_key_b64 !== suppliedKeyB64) return "invalid";
  return "host";
}
async function consumeRequest(baseUrl: string, serviceKey: string, userId: string, nonce: string, timestamp: number, limit: number): Promise<string> {
  const response = await adminRequest(baseUrl, serviceKey, "/rest/v1/rpc/jarvis_consume_cloud_request", {
    method: "POST",
    body: JSON.stringify({ p_user_id: userId, p_nonce: nonce, p_timestamp: timestamp, p_daily_limit: limit }),
  });
  if (!response.ok) return "error";
  return await response.json();
}
function extractText(provider: Provider, result: any): string {
  if (provider === "gemini") {
    const candidates = Array.isArray(result?.candidates) ? result.candidates : [];
    const parts = Array.isArray(candidates[0]?.content?.parts) ? candidates[0].content.parts : [];
    return parts.map((p: { text?: unknown }) => typeof p.text === "string" ? p.text : "").join("").trim();
  }
  if (provider === "anthropic") {
    const blocks = Array.isArray(result?.content) ? result.content : [];
    return blocks.map((b: { type?: string; text?: unknown }) => b.type === "text" && typeof b.text === "string" ? b.text : "").join("").trim();
  }
  const choices = Array.isArray(result?.choices) ? result.choices : [];
  const value = choices[0]?.message?.content;
  return typeof value === "string" ? value.trim() : "";
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
  if (rawBody.length > 32_000) return jsonResponse({ error: "request_too_large" }, 413);
  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(new TextDecoder().decode(rawBody));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("bad_body");
    body = parsed as Record<string, unknown>;
  } catch { return jsonResponse({ error: "invalid_json" }, 400); }

  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  const systemPrompt = typeof body.system_prompt === "string" ? body.system_prompt.trim() : "You are JARVIS, a capable personal AI assistant.";
  if (!prompt) return jsonResponse({ error: "missing_prompt" }, 400);
  if (prompt.length > 8000 || systemPrompt.length > 4000) return jsonResponse({ error: "prompt_too_large" }, 413);

  const hostResult = await verifyHostSignature(req, rawBody, userId, baseUrl, serviceKey).catch(() => "invalid" as const);
  if (hostResult === "invalid") return jsonResponse({ error: "host_verification_failed" }, 403);

  const nonce = req.headers.get("X-Jarvis-Host-Nonce") || crypto.randomUUID();
  const timestamp = Number(req.headers.get("X-Jarvis-Host-Timestamp") || Math.floor(Date.now() / 1000));
  // Registered host devices bypass the normal-user quota; every other authenticated user is rate limited.
  const limit = hostResult === "host" ? 1000 : 100;
  const usage = await consumeRequest(baseUrl, serviceKey, userId, nonce, timestamp, limit);
  if (usage === "replay") return jsonResponse({ error: "replay_detected" }, 409);
  if (usage === "quota") return jsonResponse({ error: "daily_quota_exceeded" }, 429);
  if (usage !== "ok") return jsonResponse({ error: "security_check_failed" }, 503);

  const requested = typeof body.provider === "string" ? body.provider.toLowerCase() : "gemini";
  const providers: Provider[] = ["gemini", "openai", "groq", "anthropic"];
  if (!providers.includes(requested as Provider)) return jsonResponse({ error: "unsupported_provider" }, 400);
  const provider = requested as Provider;
  const configs: Record<Provider, { keyName: string; model: string; url: string }> = {
    gemini: { keyName: "GEMINI_API_KEY", model: "gemini-2.5-flash", url: "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent" },
    openai: { keyName: "OPENAI_API_KEY", model: "gpt-4.1-mini", url: "https://api.openai.com/v1/chat/completions" },
    groq: { keyName: "GROQ_API_KEY", model: "llama-3.3-70b-versatile", url: "https://api.groq.com/openai/v1/chat/completions" },
    anthropic: { keyName: "ANTHROPIC_API_KEY", model: "claude-3-5-haiku-latest", url: "https://api.anthropic.com/v1/messages" },
  };
  const config = configs[provider];
  const apiKey = Deno.env.get(config.keyName);
  if (!apiKey) return jsonResponse({ error: "provider_not_configured", provider }, 503);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    let headers: Record<string, string>;
    let requestBody: Record<string, unknown>;
    if (provider === "gemini") {
      headers = { "Content-Type": "application/json", "x-goog-api-key": apiKey };
      requestBody = { contents: [{ role: "user", parts: [{ text: prompt }] }], systemInstruction: { parts: [{ text: systemPrompt }] }, generationConfig: { maxOutputTokens: 1024, temperature: 0.7 } };
    } else if (provider === "anthropic") {
      headers = { "Content-Type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" };
      requestBody = { model: config.model, max_tokens: 1024, system: systemPrompt, messages: [{ role: "user", content: prompt }] };
    } else {
      headers = { "Content-Type": "application/json", Authorization: "Bearer " + apiKey };
      requestBody = { model: config.model, messages: [{ role: "system", content: systemPrompt }, { role: "user", content: prompt }], max_tokens: 1024, temperature: 0.7 };
    }
    const upstream = await fetch(config.url, { method: "POST", headers, signal: controller.signal, body: JSON.stringify(requestBody) });
    const result = await upstream.json().catch(() => ({}));
    if (!upstream.ok) return jsonResponse({ error: "provider_request_failed", provider, status: upstream.status, message: "Provider rejected the request; check key, model access, quota, and billing." }, 502);
    const text = extractText(provider, result);
    if (!text) return jsonResponse({ error: "empty_provider_response", provider }, 502);
    return jsonResponse({ text, provider, model: config.model });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "AbortError";
    return jsonResponse({ error: timedOut ? "provider_timeout" : "provider_unavailable" }, timedOut ? 504 : 502);
  } finally { clearTimeout(timeout); }
});
