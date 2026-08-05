"use strict";

const COMPUTE_FACT_KINDS = Object.freeze([
  "compute_preparation",
  "submission",
  "inspection",
  "collection",
  "cancellation",
  "program_status",
  "parser",
]);

const FACT_KINDS = Object.freeze([
  "review",
  ...COMPUTE_FACT_KINDS,
  "render",
  "report",
  "email",
]);

const FACT_KIND_ALIASES = Object.freeze({
  preparation: "compute_preparation",
  compute_preparation: "compute_preparation",
  compute_submission: "submission",
  submission: "submission",
  status: "inspection",
  inspection: "inspection",
  artifact_collection: "collection",
  compute_collection: "collection",
  collection: "collection",
  cancel: "cancellation",
  cancellation: "cancellation",
  program: "program_status",
  program_status: "program_status",
  parser: "parser",
});

function normalizeFactKind(value) {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(FACT_KIND_ALIASES, value)
    ? FACT_KIND_ALIASES[value]
    : value;
}

module.exports = { COMPUTE_FACT_KINDS, FACT_KINDS, FACT_KIND_ALIASES, normalizeFactKind };
