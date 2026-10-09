import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { timingSafeEqual } from "node:crypto";
import { connectHost, HOST_PROTOCOL } from "./host-client.mjs";
import { require_workspace_id } from "../contracts/workspace-id.mjs";

const METHODS = new Set(["session/read", "session/attach", "input/send", "input/status", "turn/interrupt", "monitor/list", "monitor/status", "monitor/enable", "monitor/disable"]);
const MUTATIONS = new Set(["input/send", "turn/interrupt", "monitor/enable", "monitor/disable"]);
const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const authority = (host, port) => `${host.includes(":") && !host.startsWith("[") ? `[${host}]` : host}:${port}`;

/** One authenticated HTTP transport for a fixed Host session. No session state is owned here. */
export function createBrowserGateway({ peer, identity, authToken, host = "127.0.0.1" }) {
  if (typeof authToken !== "string" || !authToken) throw new Error("Browser gateway requires an auth token, including on loopback");
  require_workspace_id(identity.workspace_id);
  const streams = new Set();
  const expected = Buffer.from(`Bearer ${authToken}`);
  const server = createServer(async (request, response) => {
    const send = (status, value) => {
      response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
      response.end(JSON.stringify(value));
    };
    try {
      const address = server.address();
      const hosts = new Set([authority(host, address.port), authority(address.address, address.port)]);
      if (["127.0.0.1", "::1", "localhost"].includes(host)) hosts.add(authority("localhost", address.port));
      if (!hosts.has(request.headers.host)) return send(403, { error: "Host is not allowed" });
      if (request.headers.origin && request.headers.origin !== `http://${request.headers.host}`) return send(403, { error: "Origin is not allowed" });
      const actual = Buffer.from(request.headers.authorization || "");
      if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return send(401, { error: "Unauthorized" });
      const url = new URL(request.url, "http://localhost");
      if (request.method === "GET" && url.pathname === "/health") return send(200, { protocol: HOST_PROTOCOL, ...identity, connected: !peer.isClosed() });
      const prefix = `/v1/session/${encodeURIComponent(identity.session_id)}`;
      if (request.method === "GET" && url.pathname === `${prefix}/snapshot`) return send(200, await peer.request("session/read", identity));
      if (request.method === "GET" && url.pathname === `${prefix}/events`) {
        const snapshot = await peer.request("session/read", identity);
        response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store", Connection: "keep-alive" });
        streams.add(response);
        response.on("close", () => streams.delete(response));
        response.write(`data: ${JSON.stringify({ method: "session/snapshot", params: snapshot })}\n\n`);
        return;
      }
      if (request.method !== "POST" || url.pathname !== "/rpc") return send(404, { error: "Unknown route" });
      if (!/^application\/json(?:\s*;|$)/iu.test(request.headers["content-type"] || "")) return send(415, { error: "Content-Type must be application/json" });
      const chunks = [];
      let size = 0;
      for await (const chunk of request) {
        size += chunk.length;
        if (size > 1024 * 1024) return send(413, { error: "Request too large" });
        chunks.push(chunk);
      }
      const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!object(input) || Object.keys(input).some(key => !["id", "method", "params"].includes(key))
          || !METHODS.has(input.method) || (input.params !== undefined && !object(input.params))) {
        return send(400, { error: "Expected a supported Host {id, method, params} request" });
      }
      const params = input.params || {};
      if (Object.keys(identity).some(key => params[key] !== undefined && params[key] !== identity[key])) return send(403, { error: "Request belongs to another session" });
      const requestId = params.request_id ?? input.id;
      if (MUTATIONS.has(input.method) && (typeof requestId !== "string" || !requestId)) return send(400, { error: "Mutations require a stable request_id or id" });
      const result = await peer.request(input.method, { ...params, ...identity, ...(requestId === undefined ? {} : { request_id: requestId }) });
      send(200, { id: input.id ?? null, result });
    } catch (error) { send(400, { error: { code: error.code || "request_failed", message: error.message } }); }
  });
  const notify = event => {
    for (const stream of streams) {
      if (stream.writableLength > 1024 * 1024) { stream.destroy(); continue; }
      stream.write(`data: ${JSON.stringify(event)}\n\n`);
    }
  };
  peer.on("notification", notify);
  const disconnected = () => { for (const stream of streams) stream.end(); server.close(); server.closeAllConnections(); };
  peer.on("close", disconnected);
  server.once("close", () => { peer.off("notification", notify); peer.off("close", disconnected); });
  return server;
}

async function main(args) {
  const options = { host: "127.0.0.1", port: "8767" };
  for (let index = 0; index < args.length; index++) {
    const key = args[index].replace(/^--/u, "");
    if (!["connect", "workspace", "session-id", "host", "port", "auth-token"].includes(key) || !args[index + 1]) throw new Error(`Unknown gateway option: ${args[index]}`);
    options[key] = args[++index];
  }
  if (!options.connect?.startsWith("unix://") || !options.workspace || !options["session-id"] || !options["auth-token"]) {
    throw new Error("Gateway requires --connect unix://SOCKET, --workspace, --session-id and --auth-token");
  }
  const root = resolve(options.workspace);
  const manifest = JSON.parse(readFileSync(join(root, "workspace_manifest.json"), "utf8"));
  if (manifest?.schema_version !== "research_workspace/2" || manifest.state !== "ready" || resolve(manifest.workspace_root || "") !== root) throw new Error("Gateway workspace manifest is invalid or not admitted");
  const identity = { workspace_id: require_workspace_id(manifest.workspace_id), session_id: options["session-id"] };
  const peer = await connectHost({ socketPath: options.connect.slice(7) });
  try {
    await peer.request("session/attach", identity);
    const server = createBrowserGateway({ peer, identity, authToken: options["auth-token"], host: options.host });
    await new Promise((done, fail) => { server.once("error", fail); server.listen(Number(options.port), options.host, done); });
    server.once("close", () => peer.close());
    const stop = () => { server.close(); server.closeAllConnections(); };
    for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, stop);
    process.stdout.write(`ResearchAgent gateway: http://${authority(options.host, server.address().port)}\n`);
  } catch (error) { peer.close(); throw error; }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch(error => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
