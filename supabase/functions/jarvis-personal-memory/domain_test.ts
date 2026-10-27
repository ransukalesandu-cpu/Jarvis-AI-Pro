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
  assertEquals(validatePersonalFact({
    fact_key: "name",
    value: "Anna",
    evidence_quote: "My name is Lesandu and my sister is Anna.",
  }).ok, false);
  assertEquals(validatePersonalFact({
    fact_key: "name",
    value: "Lesandu",
    evidence_quote: "My name is Lesandu and my sister is Anna.",
  }).ok, true);
  assertEquals(validatePersonalFact({
    fact_key: "name",
    value: "ලසඳු",
    evidence_quote: "මගේ නම ලසඳු",
  }).ok, true);
  assertEquals(validatePersonalFact({
    fact_key: "siblings",
    value: "I have two siblings",
    evidence_quote: "I have two siblings.",
  }).ok, true);
  assertEquals(validatePersonalFact({
    fact_key: "family_context",
    value: "Anna",
    evidence_quote: "My sister's name is Anna.",
  }).ok, false);
});

Deno.test("rejects contact details and credentials instead of storing them", () => {
  assertTrue(isSensitiveFactContent("Email me at person@example.com"));
  assertTrue(isSensitiveFactContent("My password is hunter123"));
  assertTrue(isSensitiveFactContent("I am Muslim and prefer halal food"));
  assertTrue(isSensitiveFactContent("My medical diagnosis is sensitive"));
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
