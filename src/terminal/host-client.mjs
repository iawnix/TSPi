import { join } from "node:path";
import { hostEnvironment, privateFile } from "../host/environment.mjs";

const MAX_RESPONSE = 8 * 1024 * 1024;

export class HostError extends Error {
  constructor(code, message, uncertain = false) {
    super(message);
    this.code = code;
    this.uncertain = uncertain;
  }
}

export async function hostConnection(installRoot, env = process.env) {
  const config = await hostEnvironment(installRoot, env);
  const host = config.TS_PHONE_HOST;
  const port = config.TS_PHONE_PORT;
  if (!["127.0.0.1", "::1"].includes(host) || !/^[0-9]+$/.test(port)
    || Number(port) < 1 || Number(port) > 65535) {
    throw new HostError("invalid_host", "The terminal requires a loopback TS_PHONE_HOST and valid TS_PHONE_PORT.");
  }
  const state = config.TS_PHONE_STATE_DIR;
  let token;
  try { token = (await privateFile(join(state, "auth.token"))).trim(); }
  catch (error) {
    if (error.code !== "ENOENT") throw error;
    throw new HostError("host_not_configured", "Host credentials are missing. Configure and start TSPhoneServer first.");
  }
  if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) throw new HostError("invalid_token", "Host credential file is invalid.");
  return { baseUrl: `http://${host === "::1" ? "[::1]" : host}:${port}`, token };
}

export function sessionPath(workspaceId, sessionId) {
  return `/workspaces/${encodeURIComponent(workspaceId)}/sessions/${encodeURIComponent(sessionId)}`;
}

export class HostClient {
  #token;
  #lifetime = new AbortController();
  constructor({ baseUrl, token, timeoutMs = 25_000 }) {
    const url = new URL(baseUrl);
    if (url.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(url.hostname)
      || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
      throw new HostError("invalid_host", "Host connection must use a loopback HTTP origin.");
    }
    this.baseUrl = url.origin;
    this.#token = token;
    this.timeoutMs = timeoutMs;
  }

  async request(path, body, { signal } = {}) {
    const mutation = body !== undefined;
    const timeout = AbortSignal.timeout(this.timeoutMs);
    try {
      const response = await fetch(this.#url(path), {
        method: mutation ? "POST" : "GET", redirect: "error",
        headers: this.#headers(mutation),
        ...(mutation ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.any([this.#lifetime.signal, timeout, ...(signal ? [signal] : [])]),
      });
      const raw = await boundedText(response);
      let payload;
      try { payload = JSON.parse(raw); }
      catch { throw new HostError("invalid_response", `Host returned an invalid response (HTTP ${response.status}).`, mutation); }
      if (!response.ok) {
        throw new HostError(payload?.error?.code || "host_error",
          payload?.error?.message || `Host request failed (HTTP ${response.status}).`,
          mutation && (response.status >= 500 || payload?.error?.code === "command_ambiguous"));
      }
      if (payload?.apiVersion !== "ts-phone-api/4" || !("data" in payload)) {
        throw new HostError("protocol_mismatch", "Host API is incompatible; synchronize the TSPi package.", mutation);
      }
      return payload.data;
    } catch (error) {
      if (error instanceof HostError) throw error;
      throw new HostError("host_unreachable", mutation
        ? "Host receipt was not received. Refresh and reconcile; do not resend automatically."
        : "Cannot reach Host. Check TSPhoneServer and its connection configuration.", mutation);
    }
  }

  async *events(path, lastEventId, signal, connected = () => {}) {
    const abort = new AbortController();
    const combined = AbortSignal.any([signal, abort.signal, this.#lifetime.signal]);
    let timer;
    const heartbeat = () => {
      clearTimeout(timer);
      timer = setTimeout(() => abort.abort(), 45_000);
    };
    heartbeat();
    try {
      const response = await fetch(this.#url(`${path}/events`), {
        headers: { ...this.#headers(), ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}) },
        signal: combined, redirect: "error",
      });
      if (!response.ok || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
        throw new HostError(response.status === 401 ? "authentication_failed" : "event_stream_failed",
          `Host event stream failed (HTTP ${response.status}).`);
      }
      connected();
      const decoder = new TextDecoder();
      let buffer = "";
      for await (const bytes of response.body) {
        heartbeat();
        buffer += decoder.decode(bytes, { stream: true });
        let match;
        while ((match = /\r?\n\r?\n/.exec(buffer))) {
          const block = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          if (block.length > MAX_RESPONSE) throw new HostError("event_too_large", "Host event exceeded the limit.");
          const data = block.split(/\r?\n/).filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).replace(/^ /, "")).join("\n");
          if (!data) continue;
          const event = JSON.parse(data);
          if (event?.protocolVersion !== "ts-phone-events/3" || typeof event.id !== "string") {
            throw new HostError("invalid_event", "Host event protocol is incompatible.");
          }
          yield event;
        }
        if (buffer.length > MAX_RESPONSE) throw new HostError("event_too_large", "Host event exceeded the limit.");
      }
    } finally { clearTimeout(timer); abort.abort(); }
  }

  #url(path) {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("#")) throw new Error("Invalid API path");
    return `${this.baseUrl}/api/v4${path}`;
  }
  close() { this.#lifetime.abort(); }
  #headers(json = false) {
    return { Authorization: `Bearer ${this.#token}`, ...(json ? { "Content-Type": "application/json" } : {}) };
  }
}

async function boundedText(response) {
  let size = 0;
  const chunks = [];
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > MAX_RESPONSE) throw new Error("Host response exceeded the limit");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}
