#!/usr/bin/env node
import { piModulePath } from "../pi/source.mjs";

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
import { basename, dirname, resolve } from "node:path";

import { createSshUnixProxy, connectHost, connectHostSsh } from "../transport/host-client.mjs";
import { formatTerminalFailure } from "./errors.mjs";
import { selectSession } from "../host/session-selection.mjs";

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
  if (["--socket-path", "--workspace-id", "--workspace-root", "--state-root", "--install-root", "--package-root", "--expected-release-id", "--session-id", "--provider", "--model", "--ssh-host", "--remote-host-socket", "--remote-proxy-path", "--ssh-config", "--ssh-option"].includes(value)) {
    const next = args[++index];
    if (!next) throw new Error(`${value} requires a value`);
    const key = value.slice(2).replaceAll("-", "_");
    if (key === "ssh_option") options.ssh_option = [...(options.ssh_option || []), next];
    else options[key] = next;
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
  return { kept, provider, model };
}

async function main() {
  if (options.resume === true || piArgs.some((value) => value === "--resume" || value === "-r")) {
    throw new Error(
      "startup -r/--resume is not supported by the Host-mediated client; "
      + "open the workspace and use /resume inside the terminal",
    );
  }
  const socketPath = options.socket_path;
  const workspaceId = requireOption("workspace_id");
  const workspaceRoot = validateWorkspaceRoot(requireOption("workspace_root"));
  const native = splitNativeProviderArgs(piArgs);
  const { kept } = native;
  const provider = options.provider ?? native.provider;
  const model = options.model ?? native.model;
  if ((provider === undefined) !== (model === undefined)) throw new Error("--provider and --model must be provided together");
  const packageRoot = resolve(requireOption("package_root"));
  const releaseRoot = dirname(packageRoot);
  const expectedReleaseId = options.expected_release_id
    || (basename(packageRoot) === "agent" && basename(dirname(releaseRoot)) === "releases" ? basename(releaseRoot) : undefined);
  const remote = options.ssh_host !== undefined;
  if (remote && socketPath) throw new Error("--socket-path cannot be combined with --ssh-host");
  if (!remote && !socketPath) throw new Error("Missing terminal option --socket-path or --ssh-host");
  const remoteOptions = remote ? {
    sshHost: requireOption("ssh_host"),
    remoteSocketPath: requireOption("remote_host_socket"),
    remoteProxyPath: requireOption("remote_proxy_path"),
    sshConfig: options.ssh_config,
    sshOptions: options.ssh_option ? (Array.isArray(options.ssh_option) ? options.ssh_option : [options.ssh_option]) : [],
  } : null;
  const peer = remote
    ? await connectHostSsh({ ...remoteOptions })
    : await connectHost({ socketPath, expectedReleaseId });
  let descriptor;
  try {
    const listed = await peer.request("session/list", { workspace_id: workspaceId });
    const sessions = listed.sessions;
    const requestedId = options.session_id;
    const selected = selectSession(sessions, requestedId, options.continue === true || options.resume === true);

    const requestId = `terminal-${process.pid}-${Date.now()}`;
    if (selected) {
      const resumed = await peer.request("session/resume", {
        request_id: requestId,
        workspace_id: workspaceId,
        session_id: selected.session_id,
        ...(provider === undefined ? {} : { model: { provider, id: model } }),
        presentation: "terminal",
      });
      descriptor = resumed.client;
    } else {
      const created = await peer.request("session/create", {
        request_id: requestId,
        workspace_id: workspaceId,
        ...(requestedId ? { session_id: requestedId } : {}),
        ...(provider === undefined ? {} : { model: { provider, id: model } }),
        presentation: "terminal",
      });
      descriptor = created.client;
    }
  } finally {
    peer.close();
  }

  let appProxy;
  let hostProxy;
  try {
    if (remote) {
      hostProxy = await createSshUnixProxy({ ...remoteOptions, label: "host" });
      appProxy = await createSshUnixProxy({
        ...remoteOptions,
        remoteSocketPath: descriptor.socket_path,
        label: "pi",
      });
    }
    const connect = appProxy ? descriptorConnect({ ...descriptor, socket_path: appProxy.socketPath }) : descriptorConnect(descriptor);
    const sourceRoot = process.env.CORAGENT_PI_RUNTIME_ROOT;
    if (!sourceRoot) throw new Error("CORAGENT_PI_RUNTIME_ROOT is required for the native Pi client");
    const resolver = piModulePath("resolver", sourceRoot);
    const client = resolve(packageRoot, "apps/agent/pi/client.mjs");
    const childArgs = ["--import", resolver, client, "--connect", connect, "--session-id", descriptor.session_id, ...kept];
    process.env.CORAGENT_SESSION_CWD = workspaceRoot;
    process.env.PI_EXPERIMENTAL = "1";
    process.env.PI_SERVER_DIR = appProxy?.directory || descriptor.server_directory || dirname(descriptor.socket_path);
    process.env.CORAGENT_PACKAGE_ROOT = packageRoot;
    const child = spawn(process.execPath, childArgs, {
      cwd: workspaceRoot,
      env: {
        ...process.env,
        CORAGENT_HOST_SOCKET: hostProxy?.socketPath || socketPath,
        CORAGENT_HOST_RELEASE_ID: remote ? "" : expectedReleaseId,
        CORAGENT_WORKSPACE_ID: workspaceId,
        ...(options.install_root ? { CORAGENT_INSTALL_ROOT: options.install_root } : {}),
        ...(options.state_root ? {
          CORAGENT_STATE_ROOT: options.state_root,
          CORAGENT_DIAGNOSTIC_FILE: `${options.state_root.replace(/\/$/u, "")}/worker-diagnostics.log`,
        } : {}),
      },
      stdio: "inherit",
    });
    const result = await new Promise((resolvePromise, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => resolvePromise({ code, signal }));
    });
    process.exitCode = result.code ?? (result.signal ? 1 : 0);
  } finally {
    await appProxy?.close();
    await hostProxy?.close();
  }
}

main().catch((error) => {
  const diagnosticFile = options.state_root
    ? `${options.state_root.replace(/\/$/u, "")}/worker-diagnostics.log`
    : undefined;
  process.stderr.write(`CoRAgent: ${formatTerminalFailure(error, {
    installRoot: options.install_root,
    diagnosticFile,
  })}\n`);
  process.exitCode = 1;
});
