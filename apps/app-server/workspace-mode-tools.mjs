import { lstat, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { classify_tool_class, is_tool_class_allowed } from "../../packages/research-agent-core/mode_policy.mjs";

export const WORKSPACE_MODES = Object.freeze(["light", "research"]);

// Derived from the framework mode policy. Research-only names are retained as
// a public migration marker, but admission itself uses the shared class
// classifier below so the app server cannot silently drift from Core policy.
export const RESEARCH_ONLY_TOOL_NAMES = Object.freeze(new Set([
  "research_read",
  "research_change",
  "research_continuation",
  "research_strategy",
  "research_interpretation",
  "research_checkpoint",
  "review_run",
  "review_respond",
  "execution_dispatch",
  "analysis_run",
  "notify_send",
]));

// Retained as an internal migration marker only. It is no longer part of the
// active Agent inventory; compute_run is the sole compute entry point.
export const LIGHT_ONLY_TOOL_NAMES = Object.freeze(new Set(["light_compute"]));

/**
 * Read the immutable framework mode bound by ResearchAgent.
 *
 * A missing manifest means an older Pi-only fixture or workspace. Keep those
 * on the research tool surface for compatibility; a present manifest is
 * authoritative and invalid values fail closed.
 */
export async function readWorkspaceMode(workspaceRoot) {
  const root = resolve(requireAbsolutePath(workspaceRoot));
  const manifestPath = join(root, "workspace_manifest.json");
  let info;
  try {
    info = await lstat(manifestPath);
  } catch (error) {
    if (error?.code === "ENOENT") return "research";
    throw new Error(`workspace_manifest_unavailable: ${manifestPath}`, { cause: error });
  }
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`workspace_manifest_invalid: ${manifestPath}`);
  }
  let manifest;
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`workspace_manifest_invalid: ${manifestPath}`, { cause: error });
  }
  const mode = manifest?.workspace_mode;
  if (!WORKSPACE_MODES.includes(mode)) throw new Error(`workspace_manifest_invalid_mode: ${String(mode)}`);
  return mode;
}

export function filterWorkspaceTools(tools, workspaceMode) {
  if (!Array.isArray(tools)) throw new TypeError("tools must be an array");
  if (!WORKSPACE_MODES.includes(workspaceMode)) throw new TypeError("workspaceMode must be light or research");
  return tools.filter((tool) => isWorkspaceToolAllowed(tool?.name, workspaceMode));
}

export function filterExtensionToolNames(names, workspaceMode) {
  if (!Array.isArray(names)) return [];
  if (!WORKSPACE_MODES.includes(workspaceMode)) throw new TypeError("workspaceMode must be light or research");
  return names.filter((name) => isWorkspaceToolAllowed(name, workspaceMode));
}

function isWorkspaceToolAllowed(name, workspaceMode) {
  if (LIGHT_ONLY_TOOL_NAMES.has(name)) return false;
  return is_tool_class_allowed(workspaceMode, classify_tool_class(name));
}

function requireAbsolutePath(value) {
  if (typeof value !== "string" || !value.trim() || !value.startsWith("/")) {
    throw new TypeError("workspaceRoot must be an absolute path");
  }
  return value;
}
