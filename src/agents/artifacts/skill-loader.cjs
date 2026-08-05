"use strict";

const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const PRIVATE_SKILLS_ROOT = resolve(__dirname, "private-skills");
const PRIVATE_SKILLS = Object.freeze({
  render: "render",
  report: "research-report",
  email: "email",
});

function loadArtifactSkill(role) {
  const directory = PRIVATE_SKILLS[role];
  if (!directory) throw new Error(`No private artifact skill is registered for role: ${role}`);
  const source = readFileSync(resolve(PRIVATE_SKILLS_ROOT, directory, "SKILL.md"), "utf8");
  if (!source.trim()) throw new Error(`Private artifact skill is empty: ${directory}`);
  return source.trim();
}

module.exports = { PRIVATE_SKILLS, loadArtifactSkill };
