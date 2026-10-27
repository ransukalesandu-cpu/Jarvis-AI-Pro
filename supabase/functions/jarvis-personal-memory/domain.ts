/** Validation helpers for small, directly user-stated personal-profile facts. */

export const ALLOWED_FACT_KEYS = [
  "name",
  "siblings",
  "family_context",
  "education",
  "occupation",
  "interests",
  "preferences",
  "goals",
  "language",
  "communication_style",
] as const;

export type PersonalFactKey = typeof ALLOWED_FACT_KEYS[number];

export function normalizeEvidence(value: string): string {
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase();
}

export function isAllowedFactKey(value: unknown): value is PersonalFactKey {
  return typeof value === "string" &&
    (ALLOWED_FACT_KEYS as readonly string[]).includes(value);
}

export function isSensitiveFactContent(value: string): boolean {
  const text = String(value ?? "");
  const patterns = [
    /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/,
    /(?:\+?\d[\s().-]*){8,15}/,
    /\b(?:password|passcode|one[- ]time code|api[-_ ]?key|access token|refresh token|secret key|credit card|bank account|passport number|national id|social security|home address|street address)\b/i,
    /\b\d{1,6}\s+[\w.-]+\s+(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr)\b/i,
    /https?:\/\//i,
  ];
  return patterns.some((pattern) => pattern.test(text));
}

export function validatePersonalFact(input: {
  fact_key?: unknown;
  value?: unknown;
  evidence_quote?: unknown;
}): { ok: true; fact_key: PersonalFactKey; value: string; evidence_quote: string } |
   { ok: false; reason: string } {
  if (!isAllowedFactKey(input.fact_key)) return { ok: false, reason: "invalid_fact_key" };
  if (typeof input.value !== "string" || typeof input.evidence_quote !== "string") {
    return { ok: false, reason: "missing_fact_text" };
  }
  const value = input.value.replace(/\s+/g, " ").trim();
  const evidence_quote = input.evidence_quote.replace(/\s+/g, " ").trim();
  if (!value || value.length > 500 || !evidence_quote || evidence_quote.length > 700) {
    return { ok: false, reason: "invalid_fact_length" };
  }
  const quoteNormalized = normalizeEvidence(evidence_quote);
  if (!quoteNormalized.includes(normalizeEvidence(value))) {
    return { ok: false, reason: "fact_not_in_evidence" };
  }
  if (isSensitiveFactContent(value) || isSensitiveFactContent(evidence_quote)) {
    return { ok: false, reason: "sensitive_content_not_stored" };
  }
  return { ok: true, fact_key: input.fact_key, value, evidence_quote };
}
