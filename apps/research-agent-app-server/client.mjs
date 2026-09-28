export class AppServerClientError extends Error {
  constructor(message, { status, code, body } = {}) {
    super(message);
    this.name = "AppServerClientError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

export function create_app_server_client({ base_url, fetch_impl = globalThis.fetch, headers = {} } = {}) {
  if (typeof base_url !== "string" || base_url.length === 0) throw new TypeError("base_url is required");
  if (typeof fetch_impl !== "function") throw new TypeError("fetch_impl is required");
  const origin = base_url.replace(/\/+$/u, "");

  async function request(route, payload, method = "POST") {
    const response = await fetch_impl(`${origin}/${route}`, {
      method,
      headers: { accept: "application/json", ...(method === "POST" ? { "content-type": "application/json" } : {}), ...headers },
      ...(method === "POST" ? { body: JSON.stringify(payload ?? {}) } : {}),
    });
    let body;
    try {
      body = await response.json();
    } catch (error) {
      throw new AppServerClientError("server returned invalid JSON", { status: response.status, body: undefined });
    }
    if (!response.ok) {
      throw new AppServerClientError(body?.error?.message || `HTTP ${response.status}`, {
        status: response.status,
        code: body?.error?.code,
        body,
      });
    }
    return body;
  }

  return Object.freeze({
    health_read: () => request("health_read", {}, "GET"),
    workspace_initialize: (payload) => request("workspace_initialize", payload),
    research_initialize: (payload) => request("research_initialize", payload),
    workspace_attach: (payload) => request("workspace_attach", payload),
    workspace_admit: (payload) => request("workspace_admit", payload),
    research_admit: (payload) => request("research_admit", payload),
    session_create: (payload) => request("session_create", payload),
    session_list: (payload = {}) => request("session_list", payload),
    session_attach: (payload) => request("session_attach", payload),
    session_close: (payload) => request("session_close", payload),
    turn_route: (payload) => request("turn_route", payload),
    turn_submit: (payload) => request("turn_submit", payload),
    research_turn: (payload) => request("research_turn", payload),
    research_change: (payload) => request("research_change", payload),
    tool_describe: (payload) => request("tool_describe", payload),
    tool_invoke: (payload) => request("tool_invoke", payload),
    compute_run: (payload) => request("compute_run", payload),
    compute_cancel: (payload) => request("compute_cancel", payload),
    capability_catalog: (payload = {}) => request("capability_catalog", payload),
    capability_readiness: (payload = {}) => request("capability_readiness", payload),
    compute_catalog: (payload = {}) => request("compute_catalog", payload),
    compute_readiness: (payload = {}) => request("compute_readiness", payload),
  });
}
