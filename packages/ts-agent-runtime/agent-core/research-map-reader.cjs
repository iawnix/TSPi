"use strict";

const { existsSync, lstatSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");

// New Research Agent workspaces keep the authoritative ResearchMap projection
// in research_map/context.json. Legacy workspaces still expose research_map.json.
// Consumers receive the same map-shaped read-only document in either case.
function readResearchMap(rootValue) {
  const root = resolve(rootValue);
  const contextPath = resolve(root, "research_map", "context.json");
  const livenessPath = resolve(root, "lifecycle", "liveness.json");
  if (existsSync(contextPath)) {
    if (lstatSync(contextPath).isSymbolicLink()) throw new Error("ResearchMap context is a symbolic link");
    const context = JSON.parse(readFileSync(contextPath, "utf8"));
    if (!isPlainObject(context) || context.schema_version !== "research_map_context_1") {
      throw new Error("ResearchMap context schema is invalid");
    }
    return {
      ...context,
      schema_version: "research-map/1",
      nodes: Array.isArray(context.nodes) ? context.nodes : [],
      claims: Array.isArray(context.claims) ? context.claims : [],
    };
  }
  // A partially-created new workspace must not silently fall back to a stale
  // legacy map. The Research Agent boundary treats either state file as an
  // explicit opt-in to the context/liveness protocol.
  if (existsSync(livenessPath)) {
    if (lstatSync(livenessPath).isSymbolicLink()) throw new Error("ResearchMap liveness is a symbolic link");
    throw new Error("ResearchMap context does not exist");
  }
  const mapPath = resolve(root, "research_map.json");
  if (!existsSync(mapPath) || lstatSync(mapPath).isSymbolicLink()) return null;
  const map = JSON.parse(readFileSync(mapPath, "utf8"));
  if (!isPlainObject(map) || map.schema_version !== "research-map/1") {
    throw new Error("ResearchMap schema is invalid");
  }
  return map;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { readResearchMap };
