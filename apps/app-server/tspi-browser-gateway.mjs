import { createServer } from "node:http";
import { basename } from "node:path";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { connectHost, HOST_PROTOCOL } from "./tspi-host-client.mjs";

const options = { host: "127.0.0.1", port: "8767" };
const args = process.argv.slice(2);
for (let index = 0; index < args.length; index++) {
  const key = args[index].replace(/^--/u, "");
  if (!["connect", "workspace", "session-id", "host", "port", "auth-token"].includes(key) || !args[index + 1]) throw new Error(`Unknown gateway option: ${args[index]}`);
  options[key] = args[++index];
}
if (!["127.0.0.1", "::1", "localhost"].includes(options.host) && !options["auth-token"]) throw new Error("A non-loopback gateway requires --auth-token");
if (!options.connect?.startsWith("unix://") || !options.workspace || !options["session-id"]) throw new Error("Gateway requires --connect unix://SOCKET, --workspace and --session-id");
const identity = { workspace_id: basename(options.workspace), session_id: options["session-id"] };
const peer = await connectHost({ socketPath: options.connect.slice(7) });
await peer.request("session/attach", identity);
const streams = new Set();
peer.on("notification", (event) => {
  for (const stream of streams) {
    if (stream.writableLength > 1024 * 1024) { stream.destroy(); continue; }
    stream.write(`data: ${JSON.stringify(event)}\n\n`);
  }
});
const server = createServer(async (request, response) => {
  const send = (status, value) => { response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); response.end(JSON.stringify(value)); };
  try {
    // No CORS access is granted implicitly; configured bearer auth protects
    // remote access, and an unsolicited browser Origin is rejected locally.
    if (request.headers.origin) return send(403, { error: "Cross-origin access is not enabled" });
    if (options["auth-token"]) {
      const expected = Buffer.from(`Bearer ${options["auth-token"]}`);
      const actual = Buffer.from(request.headers.authorization || "");
      if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return send(401, { error: "Unauthorized" });
    }
    const url = new URL(request.url, "http://localhost");
    if (url.pathname === "/health") return send(200, { protocol: HOST_PROTOCOL, ...identity, connected: !peer.isClosed() });
    const prefix = `/v1/session/${encodeURIComponent(identity.session_id)}`;
    if (request.method === "GET" && url.pathname === `${prefix}/snapshot`) return send(200, await peer.request("session/read", identity));
    if (request.method === "GET" && url.pathname === `${prefix}/events`) {
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store", Connection: "keep-alive" });
      streams.add(response);
      response.on("close", () => streams.delete(response));
      response.write(`data: ${JSON.stringify({ method: "session/snapshot", params: await peer.request("session/read", identity) })}\n\n`);
      return;
    }
    if (request.method !== "POST" || !["/rpc", `${prefix}/requests`].includes(url.pathname)) return send(404, { error: "Unknown route" });
    let text = "";
    for await (const chunk of request) { text += chunk; if (Buffer.byteLength(text) > 1024 * 1024) return send(413, { error: "Request too large" }); }
    const input = JSON.parse(text);
    let method = input.method;
    let params = input.params || {};
    if (!method) {
      method = input.action === "abort" ? "turn/interrupt" : "input/send";
      params = { ...input, text: input.message, client_message_id: input.request_id, turn_id: input.operation_id, mode: input.mode === "steer" ? "steer" : "auto" };
    }
    if (!["session/read", "session/attach", "input/send", "input/status", "turn/interrupt", "monitor/list", "monitor/status", "monitor/enable", "monitor/disable"].includes(method)) return send(400, { error: "Method is unavailable on this session gateway" });
    const result = await peer.request(method, { ...params, ...identity, request_id: params.request_id || input.id || randomUUID() });
    send(200, { id: input.id ?? null, result });
  } catch (error) { send(400, { error: { code: error.code || "request_failed", message: error.message } }); }
});
server.listen(Number(options.port), options.host, () => process.stdout.write(`TSPi gateway: http://${options.host}:${server.address().port}\n`));
function stop() { for (const stream of streams) stream.end(); peer.close(); server.close(); server.closeAllConnections(); }
peer.on("close", stop);
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, stop);
