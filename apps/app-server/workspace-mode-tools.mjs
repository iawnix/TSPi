import { lstat, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { classify_tool_class, is_tool_class_allowed } from "../../packages/agent-core/mode_policy.mjs";
import { validate_workspace_files, validate_workspace_manifest } from "../../packages/agent-core/workspace.mjs";

export const WORKSPACE_MODE = "research";

// Derived from the framework mode policy. Research-only names are retained as
// a public vocabulary marker, but admission itself uses the shared class
// classifier below so the app server cannot silently drift from Core policy.
export const RESEARCH_ONLY_TOOL_NAMES = Object.freeze(new Set([
  "research_read",
  "research_change",
  "research_strategy",
  "research_interpretation",
  "research_checkpoint",
]));

/**
 * Read the immutable framework mode bound by ResearchAgent.
 *
 * Every Host workspace is initialized by the canonical workspace initializer.
 * A missing or incomplete manifest is therefore a configuration error; mode
 * selection must never fall back to a legacy Pi-only workspace.
 */
export async function readWorkspaceMode(workspaceRoot) {
  return (await readWorkspaceManifest(workspaceRoot)).workspace_mode;
}

export async function readWorkspaceManifest(workspaceRoot) {
  const root = resolve(requireAbsolutePath(workspaceRoot));
  const manifestPath = join(root, "workspace_manifest.json");
  let info;
  try {
    info = await lstat(manifestPath);
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error(`workspace_manifest_unavailable: ${manifestPath}`);
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
  try {
    // Tool inventory is a runtime boundary, so it may only be built after
    // Host admission has committed the manifest.  An admission_pending
    // workspace is an internal initialization state and cannot own a session.
    validate_workspace_manifest(manifest, root);
    if (manifest.state !== "ready") throw new Error(`workspace_admission_required: ${manifest.state}`);
    await validate_workspace_files(manifest, root);
  } catch (error) {
    if (error?.message?.startsWith("workspace_admission_required:")) throw error;
    throw new Error(`workspace_manifest_invalid: ${manifestPath}`, { cause: error });
  }
  return Object.freeze(manifest);
}

export function filterWorkspaceTools(tools, workspaceMode = WORKSPACE_MODE) {
  if (!Array.isArray(tools)) throw new TypeError("tools must be an array");
  if (workspaceMode !== WORKSPACE_MODE) throw new TypeError("workspaceMode must be research");
  return tools.filter((tool) => isWorkspaceToolAllowed(tool?.name, workspaceMode));
}

export function filterExtensionToolNames(names, workspaceMode = WORKSPACE_MODE) {
  if (!Array.isArray(names)) return [];
  if (workspaceMode !== WORKSPACE_MODE) throw new TypeError("workspaceMode must be research");
  return names.filter((name) => isWorkspaceToolAllowed(name, workspaceMode));
}

function isWorkspaceToolAllowed(name, workspaceMode) {
  return is_tool_class_allowed(workspaceMode, classify_tool_class(name));
}

function requireAbsolutePath(value) {
  if (typeof value !== "string" || !value.trim() || !value.startsWith("/")) {
    throw new TypeError("workspaceRoot must be an absolute path");
  }
  return value;
}
