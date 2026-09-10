"use strict";

const fs = require("node:fs");
const path = require("node:path");

const ROLE_DIR = path.resolve(__dirname, "roles");
const ROLE_ID = /^[a-z][a-z0-9_-]{0,63}$/;
const ROLE_KEYS = [
  "schema_version", "role_id", "revision", "title", "specialty", "description",
  "prompt_revision", "model_policy", "budget", "authority",
];

function loadReviewerRole(roleId = "general") {
  requireRoleId(roleId);
  const file = path.resolve(ROLE_DIR, `${roleId}.json`);
  if (!file.startsWith(`${ROLE_DIR}${path.sep}`)) throw new Error("reviewer role path escapes the role directory");
  let value;
  try {
    value = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    throw new Error(`unknown reviewer role: ${roleId}`, { cause: error });
  }
  return validateReviewerRole(value, roleId);
}

function validateReviewerRole(value, expectedId = undefined) {
  if (!isObject(value)) throw new Error("reviewer role must be an object");
  rejectUnknownKeys(value, ROLE_KEYS, "reviewer role");
  if (value.schema_version !== "ts-reviewer-role/1") throw new Error("unsupported reviewer role schema");
  requireRoleId(value.role_id);
  if (expectedId !== undefined && value.role_id !== expectedId) throw new Error("reviewer role identity mismatch");
  requireText(value.title, "reviewer role title", 200);
  requireText(value.specialty, "reviewer role specialty", 500);
  requireText(value.description, "reviewer role description", 2000);
  requireText(value.prompt_revision, "reviewer role prompt_revision", 128);
  if (!isObject(value.model_policy) || value.model_policy.mode !== "inherit_parent" || value.model_policy.allow_override !== false) {
    throw new Error("reviewer role model policy must inherit the parent without override");
  }
  if (!isObject(value.budget)
      || !Number.isInteger(value.budget.max_artifact_reads) || value.budget.max_artifact_reads !== 1
      || !Number.isInteger(value.budget.max_artifacts_per_read) || value.budget.max_artifacts_per_read < 1 || value.budget.max_artifacts_per_read > 4
      || !Number.isInteger(value.budget.max_result_bytes) || value.budget.max_result_bytes < 1024 || value.budget.max_result_bytes > 16384) {
    throw new Error("reviewer role budget is invalid");
  }
  if (value.authority !== "advisory") throw new Error("reviewer role authority must be advisory");
  return JSON.parse(JSON.stringify(value));
}

function requireRoleId(value) {
  if (typeof value !== "string" || !ROLE_ID.test(value)) throw new Error("reviewerRole is invalid");
  return value;
}

function requireText(value, label, max) {
  if (typeof value !== "string" || !value.trim() || value.length > max) throw new Error(`${label} is invalid`);
}

function rejectUnknownKeys(value, allowed, label) {
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function isObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

module.exports = { loadReviewerRole, validateReviewerRole };
