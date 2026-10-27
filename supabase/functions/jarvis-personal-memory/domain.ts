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
    /\b(?:medical|diagnos\w*|illness|disease|medication|prescription|mental health|depression|anxiety|disability|disorder|religion|religious|muslim|christian|hindu|buddhist|jewish|atheist|political party|political affiliation|vote for|voting preference|sexual orientation|sexuality|gender identity|race|ethnicity|salary|income|bank balance|credit score|debt|loan balance|criminal record|immigration status|date of birth|birthday|my age is)\b/i,
  ];
  return patterns.some((pattern) => pattern.test(text));
}

function selfNameSegment(quote: string): string {
  const prefixes = [
    /\bmy\s+name\s+is\s+/i,
    /\bmy\s+name's\s+/i,
    /\bcall\s+me\s+/i,
    /\bi\s+am\s+called\s+/i,
    /\bi'm\s+called\s+/i,
    /\bmage\s+nama\s+/i,
    /මගේ\s*නම\s*/,
  ];
  for (const pattern of prefixes) {
    const match = pattern.exec(quote);
    if (!match) continue;
    const tail = quote.slice(match.index + match[0].length);
    const segment = tail.split(
      /[,.;!?]|\s+(?:and|but|from|because|as|i|my|mage|mama|mata)\b|\s+(?:සහ|හා|මගේ|මම|මට)\s*/i,
    )[0];
    return normalizeEvidence(segment.replace(/^["']+|["']+$/g, ""));
  }
  return "";
}

const SIBLING_EVIDENCE =
  /\bi\s+have\b.{0,80}\b(?:sister|brother|siblings?)\b|\bmy\s+(?:sister|brother|siblings?)\b|\bonly\s+child\b|\bno\s+siblings\b|\bmage\s+(?:akka|ayya|aiya|malli|nangi|sahodara)|මගේ\s*(?:අක්කා|අයියා|මල්ලි|නංගි|සහෝදර)|මට\s*[^.!?]{0,50}(?:සහෝදර|අක්කා|අයියා|මල්ලි|නංගි)/i;
const SIBLING_IDENTIFYING =
  /\b(?:named|called|name is|name's|birthday|age is|phone|email|address|school|occupation|profession|doctor|teacher|student|works? at)\b|(?:නම|උපන්දිනය|දුරකථන|ලිපිනය)/i;

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
  if (input.fact_key === "name" &&
      selfNameSegment(evidence_quote) !== normalizeEvidence(value)) {
    return { ok: false, reason: "name_not_directly_stated" };
  }
  if (input.fact_key === "siblings" && !SIBLING_EVIDENCE.test(evidence_quote)) {
    return { ok: false, reason: "sibling_fact_not_directly_stated" };
  }
  // Don't retain another family member's identifying information even if an
  // extractor labels it as a generic family_context or preference.
  if (SIBLING_EVIDENCE.test(evidence_quote) && SIBLING_IDENTIFYING.test(evidence_quote)) {
    return { ok: false, reason: "sibling_identifying_details_not_stored" };
  }
  if (isSensitiveFactContent(value) || isSensitiveFactContent(evidence_quote)) {
    return { ok: false, reason: "sensitive_content_not_stored" };
  }
  return { ok: true, fact_key: input.fact_key, value, evidence_quote };
}
