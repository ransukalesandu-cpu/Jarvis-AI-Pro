import {
  isAllowedFactKey,
  isSensitiveFactContent,
  normalizeEvidence,
  validatePersonalFact,
} from "./domain.ts";
import { assertEquals } from "jsr:@std/assert";

Deno.test("only allowlisted, directly grounded profile keys are accepted", () => {
  assertEquals(isAllowedFactKey("name"), true);
  assertEquals(isAllowedFactKey("siblings"), true);
  assertEquals(isAllowedFactKey("password"), false);
  assertEquals(isAllowedFactKey("medical_history"), false);
});

Deno.test("user-name candidates must match the name immediately after a self-name cue", () => {
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
});

Deno.test("sibling presence is accepted but sibling-identifying detail is rejected", () => {
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

Deno.test("rejects contact details, credentials and sensitive categories", () => {
  assertEquals(isSensitiveFactContent("Email me at person@example.com"), true);
  assertEquals(isSensitiveFactContent("My password is hunter123"), true);
  assertEquals(isSensitiveFactContent("I am Muslim and prefer halal food"), true);
  assertEquals(isSensitiveFactContent("My medical diagnosis is sensitive"), true);
  assertEquals(isSensitiveFactContent("I have two siblings"), false);
  assertEquals(validatePersonalFact({
    fact_key: "family_context",
    value: "person@example.com",
    evidence_quote: "My email is person@example.com",
  }).ok, false);
});

Deno.test("normalization handles whitespace and unicode consistently", () => {
  assertEquals(normalizeEvidence("  My   name is  Lē sandu "), "my name is lē sandu");
});
