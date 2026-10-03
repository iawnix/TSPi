import { lstatSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { create_python_kernel_bridge } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";

/**
 * Route native Research tools through the canonical Python command boundary.
 *
 * The Native Host is a transport adapter. It must not maintain a second
 * ResearchMap serializer, operation catalog, or detail/evidence projection.
 */
export function isFilesystemResearchWorkspace(root) {
  const workspaceRoot = resolve(root);
  const manifestPath = join(workspaceRoot, "workspace_manifest.json");
  if (!isPhysicalFile(manifestPath)
    || !isPhysicalFile(join(workspaceRoot, "research_map", "context.json"))
    || !isPhysicalFile(join(workspaceRoot, "lifecycle", "liveness.json"))) return false;
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    return manifest?.schema_version === "research_state_workspace_1"
      && manifest.workspace_mode === "research"
      && manifest.state === "ready";
  } catch {
    return false;
  }
}

function isPhysicalFile(path) {
  try {
    const stat = lstatSync(path);
    return stat.isFile() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
}

export async function executeFilesystemResearchCommand(command, root, params = {}) {
  const workspaceRoot = resolve(root);
  const bridge = create_python_kernel_bridge({ workspace_root: workspaceRoot });
  try {
    if (!isFilesystemResearchWorkspace(workspaceRoot)) {
      throw new Error("research workspace requires the canonical admitted filesystem layout");
    }
    return await bridge.execute_command(command, params);
  } finally {
    await bridge.close();
  }
}
