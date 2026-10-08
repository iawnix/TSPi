/** Workspace initialization boundary shared by the Host and Research State. */
export const WORKSPACE_PORT_VERSION = "workspace_port_1";
const METHODS = ["initialize_workspace", "attach_workspace", "admit_workspace"];

export function create_workspace_port(implementation) {
  if (!implementation || typeof implementation !== "object") {
    throw new TypeError(`${WORKSPACE_PORT_VERSION} must be an object`);
  }
  for (const method of METHODS) {
    if (typeof implementation[method] !== "function") {
      throw new TypeError(`${WORKSPACE_PORT_VERSION} is missing ${method}()`);
    }
  }
  const exposed = Object.fromEntries(Object.entries(implementation).map(([key, value]) => [
    key, typeof value === "function" ? value.bind(implementation) : value,
  ]));
  for (const method of METHODS) exposed[method] = implementation[method].bind(implementation);
  return Object.freeze({ ...exposed, protocol_version: WORKSPACE_PORT_VERSION });
}
