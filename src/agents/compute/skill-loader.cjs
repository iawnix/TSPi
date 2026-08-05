"use strict";

const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const PRIVATE_SKILLS_ROOT = resolve(__dirname, "private-skills");
const PRIVATE_BACKEND_SKILLS = Object.freeze({
  gaussian: "backend-gaussian",
  ase_neb: "backend-ase",
  rdkit: "backend-rdkit",
  xtb: "backend-xtb",
  qbics_dmecp: "backend-qbics",
});

function loadBackendSkill(backend) {
  const directory = PRIVATE_BACKEND_SKILLS[backend];
  if (!directory) throw new Error(`No private backend skill is registered for: ${backend}`);
  const source = readFileSync(resolve(PRIVATE_SKILLS_ROOT, directory, "SKILL.md"), "utf8");
  return stripFrontmatter(source).trim();
}

function stripFrontmatter(source) {
  return source.replace(/^---\s*\n[\s\S]*?\n---\s*\n/, "");
}

module.exports = { PRIVATE_BACKEND_SKILLS, loadBackendSkill };
