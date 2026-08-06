"use strict";

const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const COMMON_POLICY_PATH = resolve(__dirname, "policy.md");
const ROLE_POLICIES_ROOT = resolve(__dirname, "roles");
const ROLE_POLICY_FILES = Object.freeze({
  render: "render.md",
  report: "report.md",
  email: "email.md",
});

function loadArtifactPolicy(role) {
  const filename = ROLE_POLICY_FILES[role];
  if (!filename) throw new Error(`No artifact role policy is registered for: ${role}`);
  return [
    readPolicy(COMMON_POLICY_PATH, "common artifact"),
    readPolicy(resolve(ROLE_POLICIES_ROOT, filename), `${role} role`),
  ].join("\n\n");
}

function readPolicy(path, label) {
  const source = readFileSync(path, "utf8").trim();
  if (!source) throw new Error(`Artifact policy is empty: ${label}`);
  return source;
}

module.exports = { ROLE_POLICY_FILES, loadArtifactPolicy };
