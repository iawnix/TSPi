"use strict";

const REVIEW_FACT_KINDS = Object.freeze(["review"]);
const COMPUTE_FACT_KINDS = Object.freeze([
  "compute_preparation",
  "submission",
  "inspection",
  "collection",
  "cancellation",
  "parser",
]);
const FACT_KINDS = Object.freeze([...REVIEW_FACT_KINDS, ...COMPUTE_FACT_KINDS]);

module.exports = { COMPUTE_FACT_KINDS, FACT_KINDS, REVIEW_FACT_KINDS };
