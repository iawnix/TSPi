import { create_jsonl_subprocess_transport } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";

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
