"use strict";

const { validateAgentResult, validateAgentTask } = require("../../agent-core/agent-protocol.cjs");
const { validateReviewerRole } = require("./roles.cjs");

function aggregateReviewResults({ task, reviewerResults }) {
  const normalizedTask = validateAgentTask(task);
  if (normalizedTask.role !== "review") throw new Error("review aggregation requires a review task");
  if (!Array.isArray(reviewerResults) || reviewerResults.length < 1 || reviewerResults.length > 8) {
    throw new Error("reviewerResults must contain one to eight results");
  }
  const rows = reviewerResults.map((entry, index) => normalizeEntry(entry, normalizedTask, index));
  const eligible = rows.filter((row) => ["success", "partial"].includes(row.result.outcome));
  const signatures = new Set(eligible.map((row) => opinionSignature(row.result)));
  const disagreement = eligible.length > 1 && signatures.size > 1;
  const failed = rows.filter((row) => ["failure", "not_run"].includes(row.result.outcome));
  const outcome = eligible.length === 0
    ? (failed.some((row) => row.result.outcome === "failure") ? "failure" : "not_run")
    : (eligible.some((row) => row.result.outcome === "partial") || failed.length || disagreement ? "partial" : "success");
  return {
    schema_version: "ts-review-aggregate/1",
    task_id: normalizedTask.task_id,
    target_claim_id: normalizedTask.scope.claim_refs[0] || null,
    outcome,
    reviewer_roles: rows.map((row) => row.reviewer_role).sort(),
    reviews: rows.map((row) => ({
      reviewer_role: row.reviewer_role,
      outcome: row.result.outcome,
      summary: row.result.summary,
      facts: row.result.facts,
      payload: row.result.payload,
      limitations: row.result.limitations,
      failure: row.failure,
    })),
    disagreements: disagreement ? [{
      reviewer_roles: eligible.map((row) => row.reviewer_role).sort(),
      opinions: eligible.map((row) => ({ reviewer_role: row.reviewer_role, signature: opinionSignature(row.result) })),
    }] : [],
    failures: rows.filter((row) => row.failure).map((row) => ({ reviewer_role: row.reviewer_role, failure: row.failure })),
  };
}

function normalizeEntry(entry, task, index) {
  if (!isObject(entry)) throw new Error(`reviewerResults[${index}] must be an object`);
  const reviewerRole = typeof entry.reviewer_role === "string" ? entry.reviewer_role : "";
  const role = validateReviewerRole(entry.role_descriptor, reviewerRole);
  let result = null;
  let failure = null;
  if (entry.result !== undefined && entry.result !== null) {
    result = validateAgentResult(entry.result, task);
  } else {
    if (!isObject(entry.failure)) throw new Error(`reviewerResults[${index}] requires result or failure`);
    failure = sanitizeFailure(entry.failure);
  }
  return { reviewer_role: role.role_id, role_descriptor: role, result: result || failedResult(task, failure), failure };
}

function failedResult(task, failure) {
  return {
    outcome: failure?.kind === "not_run" ? "not_run" : "failure",
    summary: failure?.message || "Reviewer failed before producing a result.",
    facts: [], payload: { missing_evidence: [], conflicts: [], options: [] }, limitations: [],
  };
}

function opinionSignature(result) {
  return JSON.stringify({
    outcome: result.outcome,
    facts: result.facts.map((fact) => ({ statement: fact.statement, status: fact.status, basis_refs: [...fact.basis_refs].sort() })),
    missing_evidence: result.payload.missing_evidence,
    conflicts: result.payload.conflicts,
  });
}

function sanitizeFailure(value) {
  if (!isObject(value) || typeof value.kind !== "string" || typeof value.message !== "string") throw new Error("review failure must contain kind and message");
  if (!/^[a-z][a-z0-9_.-]{1,63}$/.test(value.kind) || !value.message.trim() || value.message.length > 2000) throw new Error("review failure is invalid");
  return { kind: value.kind, message: value.message };
}

function isObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

module.exports = { aggregateReviewResults, opinionSignature };
