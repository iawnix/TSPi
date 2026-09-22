#!/usr/bin/env node

/*
 * Host-mediated native Pi client.
 *
 * The Host owns session selection and the durable Pi runtime. This process is
 * deliberately a small adapter: it never creates a worker, a PTY, or a tmux
 * session. Once the Host returns its local connection descriptor, Pi's own
 * experimental client/TUI is exec'd directly against that socket.
 */
import { spawn } from "node:child_process";
import { lstatSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { connectHost } from "./tspi-host-client.mjs";

const args = process.argv.slice(2);
const options = {};
const piArgs = [];
let separator = false;

for (let index = 0; index < args.length; index += 1) {
  const value = args[index];
  if (separator) {
    piArgs.push(value);
    continue;
  }
  if (value === "--") {
    separator = true;
    continue;
  }
  if (value === "--continue" || value === "-c") {
    options.continue = true;
    continue;
  }
  if (value === "--resume" || value === "-r") {
    options.resume = true;
    continue;
  }
  if (["--socket-path", "--workspace-id", "--workspace-root", "--state-root", "--install-root", "--package-root", "--session-id", "--provider", "--model"].includes(value)) {
    const next = args[++index];
    if (!next) throw new Error(`${value} requires a value`);
    options[value.slice(2).replaceAll("-", "_")] = next;
    continue;
  }
  if (value.startsWith("--provider=") || value.startsWith("--model=")) {
    const [key, ...parts] = value.slice(2).split("=");
    options[key.replaceAll("-", "_")] = parts.join("=");
    continue;
  }
  // Presentation/plugin flags belong to the native Pi client. They are kept
  // in the child argv and are never interpreted by the Host adapter.
  piArgs.push(value);
}

function requireOption(name) {
  const value = options[name];
  if (typeof value !== "string" || value.length === 0) throw new Error(`Missing terminal option --${name.replaceAll("_", "-")}`);
  return value;
}

function validateWorkspaceRoot(value) {
  const root = resolve(value);
  const info = lstatSync(root);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`Workspace root must be a regular directory: ${root}`);
  return root;
}

function descriptorConnect(descriptor) {
  if (!descriptor || descriptor.transport !== "unix" || typeof descriptor.socket_path !== "string" || !descriptor.socket_path.startsWith("/")) {
    throw new Error("Host returned an invalid Pi connection descriptor");
  }
  const encodedPath = descriptor.socket_path.split("/").map((part) => encodeURIComponent(part)).join("/");
  return `unix://${encodedPath}`;
}

function selectSession(sessions, sessionId, shouldContinue) {
  if (sessionId) {
    const exact = sessions.find((item) => item.session_id === sessionId);
    if (!exact) throw new Error(`Session is not present in workspace: ${sessionId}`);
    return exact;
  }
  const live = sessions.find((item) => item.online === true);
  if (live) return live;
  if (shouldContinue) {
    const writable = sessions.filter((item) => item.read_only !== true && item.format === "pi-harness");
    return writable[0] || null;
  }
  return null;
}

function splitNativeProviderArgs(values) {
  // A caller may put model flags after `--`; move them to Host model/select so
  // the native client does not reject model selection on an explicit socket.
  const kept = [];
  let provider;
  let model;
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index];
    if (value === "--provider" || value === "--model") {
      const next = values[++index];
      if (!next) throw new Error(`${value} requires a value`);
      if (value === "--provider") provider = next;
      else model = next;
    } else if (value.startsWith("--provider=") || value.startsWith("--model=")) {
      const [key, ...parts] = value.slice(2).split("=");
      if (key === "provider") provider = parts.join("=");
      else model = parts.join("=");
    } else {
      kept.push(value);
    }
  }
  if ((provider === undefined) !== (model === undefined)) throw new Error("--provider and --model must be provided together");
  return { kept, provider, model };
}

async function main() {
  const socketPath = requireOption("socket_path");
  const workspaceId = requireOption("workspace_id");
  const workspaceRoot = validateWorkspaceRoot(requireOption("workspace_root"));
  const { kept, provider, model } = splitNativeProviderArgs(piArgs);
  const peer = await connectHost({ socketPath });
  let descriptor;
  try {
    const listed = await peer.request("session/list", { workspace_id: workspaceId });
    const sessions = Array.isArray(listed) ? listed : listed?.sessions || [];
    const requestedId = options.session_id;
    const selected = selectSession(sessions, requestedId, options.continue === true || options.resume === true);

    const requestId = `terminal-${process.pid}-${Date.now()}`;
    if (selected) {
      const resumed = await peer.request("session/resume", {
        request_id: requestId,
        workspace_id: workspaceId,
        session_id: selected.session_id,
        presentation: "terminal",
      });
      descriptor = resumed.client;
    } else {
      const created = await peer.request("session/create", {
        request_id: requestId,
        workspace_id: workspaceId,
        ...(requestedId ? { session_id: requestedId } : {}),
        ...(provider === undefined ? {} : { provider, model }),
        presentation: "terminal",
      });
      descriptor = created.client;
    }
    if (provider !== undefined && model !== undefined) {
      await peer.request("model/select", {
        request_id: `model-${process.pid}-${Date.now()}`,
        workspace_id: workspaceId,
        session_id: descriptor.session_id,
        provider,
        model,
      });
    }
  } finally {
    peer.close();
  }

  const connect = descriptorConnect(descriptor);
  const sourceRoot = process.env.TSPI_PI_SOURCE;
  if (!sourceRoot) throw new Error("TSPI_PI_SOURCE is required for the native Pi client");
  const resolver = resolve(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts");
  const packageRoot = requireOption("package_root");
  const client = resolve(packageRoot, "apps/app-server/pi-native-client.mjs");
  const childArgs = ["--import", resolver, client, "--connect", connect, "--session-id", descriptor.session_id, ...kept];
  process.env.TSPI_SESSION_CWD = workspaceRoot;
  process.env.PI_EXPERIMENTAL = "1";
  process.env.PI_SERVER_DIR = descriptor.server_directory || dirname(descriptor.socket_path);
  process.env.TSPI_PACKAGE_ROOT = packageRoot;
  process.env.TSPI_NATIVE_WRITES = "1";
  const child = spawn(process.execPath, childArgs, { cwd: workspaceRoot, env: process.env, stdio: "inherit" });
  child.once("error", (error) => {
    process.stderr.write(`TSPi: ${error.message}\n`);
    process.exitCode = 1;
  });
  child.once("exit", (code, signal) => {
    process.exitCode = code ?? (signal ? 1 : 0);
  });
}

main().catch((error) => {
  process.stderr.write(`TSPi: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
