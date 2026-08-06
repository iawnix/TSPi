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

module.exports = { COMPUTE_FACT_KINDS, FACT_KINDS };
