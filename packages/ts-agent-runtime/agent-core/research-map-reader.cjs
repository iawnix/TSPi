"use strict";

const { existsSync, lstatSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");

// The Agent Runtime consumes the same canonical read model as the Research
// Kernel. It must never silently fall back to research_map.json, because that
// would create a second authority after a workspace has migrated.
function readResearchMap(rootValue) {
  const root = resolve(rootValue);
  const manifestPath = resolve(root, "workspace_manifest.json");
  const contextPath = resolve(root, "research_map", "context.json");
  const livenessPath = resolve(root, "lifecycle", "liveness.json");
  if (!existsSync(manifestPath) || lstatSync(manifestPath).isSymbolicLink()) {
    throw new Error("workspace manifest is required");
  }
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  if (!isPlainObject(manifest) || manifest.schema_version !== "research_agent_workspace_1") {
    throw new Error("workspace manifest schema is invalid");
  }
  if (manifest.workspace_mode === "light") return null;
  if (manifest.workspace_mode !== "research") throw new Error("workspace mode is invalid");
  if (!existsSync(contextPath) || lstatSync(contextPath).isSymbolicLink()) {
    throw new Error("ResearchMap context is missing or symbolic");
  }
  if (!existsSync(livenessPath) || lstatSync(livenessPath).isSymbolicLink()) {
    throw new Error("ResearchMap liveness is missing or symbolic");
  }
  const context = JSON.parse(readFileSync(contextPath, "utf8"));
  const liveness = JSON.parse(readFileSync(livenessPath, "utf8"));
  if (!isPlainObject(context) || context.schema_version !== "research_map_context_1") {
    throw new Error("ResearchMap context schema is invalid");
  }
  if (!isPlainObject(liveness) || liveness.schema_version !== "research_liveness_1") {
    throw new Error("ResearchMap liveness schema is invalid");
  }
  if (context.workspace_mode !== "research" || context.workspace_id !== manifest.workspace_id
      || liveness.workspace_id !== manifest.workspace_id) {
    throw new Error("ResearchMap workspace identity is inconsistent");
  }
  if (!Number.isInteger(context.revision) || context.revision < 0 || liveness.revision !== context.revision) {
    throw new Error("ResearchMap revision is inconsistent");
  }
  for (const field of ["phases", "claims", "nodes", "findings", "gates"]) {
    if (!Array.isArray(context[field])) throw new Error(`ResearchMap ${field} must be an array`);
  }
  return { ...context, schema_version: "research-map/1" };
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { readResearchMap };
