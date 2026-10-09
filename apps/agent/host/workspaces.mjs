import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { protocolError } from "../transport/host-client.mjs";
import { create_workspace_initializer } from "./workspace.mjs";
import { cleanRequest } from "./validation.mjs";
import { create_jsonl_subprocess_transport } from "../bridge/transport.mjs";

/** Host-owned catalog uses the same implementation as Web and Monitor. */
export function createWorkspaceCatalog(workspaceRoot, { python } = {}) {
  let bridge;
  const request = async (operation, params = {}) => {
    bridge ||= create_jsonl_subprocess_transport({ ...(python ? { command: python } : {}) });
    return bridge.request("workspace_catalog", { ...params, workspace_root: workspaceRoot, operation });
  };
  return {
    list: async () => (await request("list")).workspaces,
    resolve: (workspace_id, options = {}) => request("resolve", { workspace_id, ...options }),
    register: (source_roots, labels) => request("register", { source_roots, labels }),
    close: async () => { await bridge?.close(); bridge = undefined; },
  };
}

export function createHostWorkspaces(workspaceCatalog) {
  const workspaceInitializer = create_workspace_initializer();
  async function workspace(workspaceId, { allowMissing = false, attach = false } = {}) {
    return (await workspaceCatalog.resolve(workspaceId, { allow_missing: allowMissing, attach })).source_root;
  }
  async function listWorkspaces() {
    return (await workspaceCatalog.list()).map(row => ({ workspace_id: row.workspace_id, name: row.label, root: row.source_root }));
  }

  async function handle(method, params, deduplicate) {
    if (method === "workspace/list") return { workspaces: await listWorkspaces() };
    if (method === "workspace/attach") {
      const root = await workspace(params.workspace_id, { attach: true });
      const manifest = JSON.parse(await readFile(join(root, "workspace_manifest.json"), "utf8"));
      if (!manifest) throw protocolError("workspace_not_found", `Workspace does not exist: ${params.workspace_id}`);
      return { workspace: { workspace_id: manifest.workspace_id, name: manifest.workspace_id, root, workspace_mode: manifest.workspace_mode, state: manifest.state } };
    }
    if (method === "workspace/create") {
      const root = await workspace(params.workspace_id, { allowMissing: true });
      return deduplicate(method, params.request_id, cleanRequest(params), async () => {
        const initialized = await workspaceInitializer.initialize_workspace({
          workspace_root: root,
          workspace_id: params.workspace_id,
          workspace_mode: "research",
        });
        const manifest = await workspaceInitializer.admit_workspace(root);
        await workspaceCatalog.register([root]);
        return { workspace: { workspace_id: manifest.workspace_id, name: manifest.workspace_id, root, workspace_mode: manifest.workspace_mode, state: manifest.state } };
      });
    }
    throw protocolError("method_not_found", `Unsupported Host method: ${method}`);
  }
  return { workspace, listWorkspaces, handle };
}
