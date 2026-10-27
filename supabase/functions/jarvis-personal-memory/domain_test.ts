import {
  isAllowedFactKey,
  isSensitiveFactContent,
  normalizeEvidence,
  validatePersonalFact,
} from "./domain.ts";
import { assertEquals, assertFalse, assertTrue } from "jsr:@std/assert";

Deno.test("only allowlisted, directly grounded profile keys are accepted", () => {
  assertTrue(isAllowedFactKey("name"));
  assertTrue(isAllowedFactKey("siblings"));
  assertFalse(isAllowedFactKey("password"));
  assertFalse(isAllowedFactKey("medical_history"));
});

Deno.test("profile fact value must appear in user's evidence quote", () => {
  assertEquals(validatePersonalFact({
    fact_key: "name",
    value: "Lesandu",
    evidence_quote: "My name is Lesandu.",
  }).ok, true);
  assertEquals(validatePersonalFact({
    fact_key: "name",
    value: "Peter",
    evidence_quote: "My name is Lesandu.",
  }).ok, false);
});

Deno.test("rejects contact details and credentials instead of storing them", () => {
  assertTrue(isSensitiveFactContent("Email me at person@example.com"));
  assertTrue(isSensitiveFactContent("My password is hunter123"));
  assertFalse(isSensitiveFactContent("I have two siblings"));
  assertEquals(validatePersonalFact({
    fact_key: "family_context",
    value: "person@example.com",
    evidence_quote: "My email is person@example.com",
  }).ok, false);
});

Deno.test("normalization handles whitespace and unicode consistently", () => {
  assertEquals(normalizeEvidence("  My   name is  Lē sandu "), "my name is lē sandu");
});
