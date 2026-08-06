"use strict";

const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const COMMON_POLICY_PATH = resolve(__dirname, "policy.md");
const BACKEND_POLICIES_ROOT = resolve(__dirname, "backends");
const BACKEND_POLICY_FILES = Object.freeze({
  gaussian: "gaussian.md",
  ase_neb: "ase.md",
  rdkit: "rdkit.md",
  xtb: "xtb.md",
  crest: "crest.md",
  qbics_dmecp: "qbics.md",
});

function loadComputePolicy(backend) {
  const filename = BACKEND_POLICY_FILES[backend];
  if (!filename) throw new Error(`No compute backend policy is registered for: ${backend}`);
  return [
    readPolicy(COMMON_POLICY_PATH, "common compute"),
    readPolicy(resolve(BACKEND_POLICIES_ROOT, filename), `${backend} backend`),
  ].join("\n\n");
}

function readPolicy(path, label) {
  const source = readFileSync(path, "utf8").trim();
  if (!source) throw new Error(`Compute policy is empty: ${label}`);
  return source;
}

module.exports = { BACKEND_POLICY_FILES, loadComputePolicy };
