"use strict";

const { normalizeFactKind } = require("./fact-kinds.cjs");

function normalizeAgentResultInput(value, options = {}) {
  if (!isPlainObject(value)) return value;
  const normalized = { ...value };
  if (normalized.outcome === "completed") normalized.outcome = "success";
  if (!Array.isArray(normalized.facts)) return normalized;

  const resolveFactRef = typeof options.resolveFactRef === "function"
    ? options.resolveFactRef
    : (ref) => ref;
  normalized.facts = normalized.facts.map((fact, index) => {
    if (!isPlainObject(fact)) return fact;
    const normalizedFact = { ...fact };
    normalizedFact.kind = normalizeFactKind(normalizedFact.kind);
    if (
      Object.prototype.hasOwnProperty.call(normalizedFact, "artifact_ref")
      && !Object.prototype.hasOwnProperty.call(normalizedFact, "basis_refs")
      && typeof normalizedFact.artifact_ref === "string"
      && normalizedFact.artifact_ref.trim()
    ) {
      const ref = normalizedFact.artifact_ref.trim();
      delete normalizedFact.artifact_ref;
      normalizedFact.basis_refs = [resolveFactRef(ref, index)];
    }
    if (Array.isArray(normalizedFact.basis_refs)) {
      normalizedFact.basis_refs = normalizedFact.basis_refs.map((ref) => (
        typeof ref === "string" ? resolveFactRef(ref, index) : ref
      ));
    }
    return normalizedFact;
  });
  return normalized;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { normalizeAgentResultInput };
