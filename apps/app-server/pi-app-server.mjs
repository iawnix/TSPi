import { execFileSync, spawn } from "node:child_process";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const { mode, wrapper, forwarded } = parseWrapperArguments(process.argv.slice(2));
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const pinPath = join(packageRoot, "config/pi-source.json");
const pin = JSON.parse(readFileSync(pinPath, "utf8"));
const managedSource = process.env.TSPI_INSTALL_ROOT
  ? join(resolve(process.env.TSPI_INSTALL_ROOT), ".pi/runtime-cache/pi", pin.commit)
  : undefined;
const configuredRoot = wrapper.sourceRoot || process.env.TSPI_PI_SOURCE || managedSource;
if (!configuredRoot) {
  throw new Error("managed Pi source is unavailable; reinstall TSPi or pass --source-root");
}
const sourceRoot = resolve(configuredRoot);
if (!existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/cli.ts"))) {
  throw new Error(`Pi source does not contain the experimental CLI: ${sourceRoot}`);
}
if (!existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/client-runtime.ts"))) {
  throw new Error(`Pi source does not contain the remote client runtime: ${sourceRoot}`);
}
const commit = execFileSync("git", ["-C", sourceRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (commit !== pin.commit) throw new Error(`Pi source commit mismatch: expected ${pin.commit}, found ${commit}`);
const processSource = join(sourceRoot, "packages/coding-agent/src/experimental/process.ts");
if (!readFileSync(processSource, "utf8").includes("PI_SESSION_WORKER_ENTRY")) {
  throw new Error("Pi source is missing the TSPi Worker entrypoint patch; run prepare_pi_source.py --apply-worker-patch");
}
// The Host owns sessions, workers, tools, and replicated state. The terminal
// is a first-class remote client and delegates its interactive presentation to
// Pi's native client TUI. Presentation facets are requested by the client and
// loaded into the session worker profile by the Host; they are not a Host-wide
// default plugin profile.
const presentationPackage = join(packageRoot, "extensions/pi/tui-package");
const hasPresentationPackage = forwarded.some((value, index) =>
  (value === "-e" || value === "--plugin") && forwarded[index + 1] === presentationPackage,
);
const piForwarded = mode === "client"
  ? (hasPresentationPackage ? forwarded : ["-e", presentationPackage, ...forwarded])
  : forwarded;
const args = mode === "client"
  ? [join(packageRoot, "apps/app-server/pi-native-client.mjs"), ...piForwarded]
  : [join(sourceRoot, "packages/coding-agent/src/experimental/cli.ts"), mode, ...piForwarded];
const workspaceRoot = wrapper.workspace ? resolve(wrapper.workspace) : undefined;
if (workspaceRoot) {
  if (!existsSync(workspaceRoot)) throw new Error(`TSPi workspace does not exist: ${workspaceRoot}`);
  const workspaceStat = lstatSync(workspaceRoot);
  if (!workspaceStat.isDirectory() || workspaceStat.isSymbolicLink()) {
    throw new Error(`TSPi workspace must be a regular directory: ${workspaceRoot}`);
  }
}
if (mode === "server" && !workspaceRoot) throw new Error("native TSPi server requires --workspace");
if (mode === "client" && workspaceRoot) throw new Error("--workspace is not valid in client mode");
const childEnv = {
  ...process.env,
  PI_EXPERIMENTAL: "1",
  TSPI_PI_SOURCE: sourceRoot,
  TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT || packageRoot,
  PI_SESSION_WORKER_ENTRY: join(packageRoot, "apps/app-server/pi-session-worker.mjs"),
  TSPI_WORKSPACE_BOOTSTRAP: join(packageRoot, "scripts/ts_workspace.py"),
  TSPI_WORKSPACE_PYTHON: process.env.TS_AGENT_PYTHON || "python3",
  TSPI_NATIVE_WRITES: "1",
};
if (wrapper.directory) childEnv.PI_SERVER_DIR = resolve(wrapper.directory);
if (mode === "gateway") {
  // The gateway attaches to Pi's TypeScript source services directly. Install
  // Pi's source aliases before importing the runtime so package imports cannot
  // fall through to an unrelated globally installed Pi release.
  Object.assign(process.env, childEnv);
  await import(pathToFileURL(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")).href);
  const { runGatewayCli } = await import("./pi-session-control-server.mjs");
  await runGatewayCli({ sourceRoot, workspaceRoot, arguments_: forwarded });
  process.exit(0);
}
const child = spawn(process.execPath, ["--import", join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts"), ...args], {
  cwd: mode === "client" ? (process.env.TSPI_SESSION_CWD || process.cwd()) : (workspaceRoot || sourceRoot),
  env: childEnv,
  stdio: "inherit",
});
const link = mode === "server" ? startLinkHost(wrapper, forwarded, childEnv) : undefined;
const monitor = mode === "server" && workspaceRoot
  ? startMonitorWorker(wrapper, forwarded, childEnv, workspaceRoot, packageRoot)
  : undefined;
let exiting = false;
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => {
  exiting = true;
  link?.kill(signal);
  monitor?.kill(signal);
  child.kill(signal);
});
child.once("exit", (code, signal) => {
  exiting = true;
  link?.kill("SIGTERM");
  monitor?.kill("SIGTERM");
  process.exit(code ?? (signal ? 1 : 0));
});
link?.once("exit", (code, signal) => {
  if (exiting) return;
  process.stderr.write(`TSPi Link Host exited unexpectedly (${code ?? signal ?? "unknown"})\n`);
  child.kill("SIGTERM");
});

function startLinkHost(wrapper, forwarded, env) {
  const relayUrl = process.env.TSPI_LINK_URL?.trim();
  const tokenFile = process.env.TSPI_LINK_HOST_TOKEN_FILE?.trim();
  if (!relayUrl && !tokenFile) return undefined;
  if (!relayUrl || !tokenFile) throw new Error("TSPI_LINK_URL and TSPI_LINK_HOST_TOKEN_FILE must be configured together");
  const serverId = forwardedOption(forwarded, "--server-id");
  if (!wrapper.directory || !serverId) throw new Error("TSPi Link Host requires the managed App Server directory and identity");
  return spawn(process.execPath, [
    join(packageRoot, "apps/app-server/tspi-link-host.mjs"),
    "--relay-url", relayUrl,
    "--token-file", tokenFile,
    "--socket-path", join(resolve(wrapper.directory), `${serverId}.sock`),
  ], { cwd: workspaceRoot || sourceRoot, env, stdio: "inherit" });
}

function startMonitorWorker(wrapper, forwarded, env, workspaceRoot, packageRoot) {
  if (process.env.TSPI_MONITOR_DISABLED === "1") return undefined;
  const args = [
    join(packageRoot, "apps/app-server/pi-monitor-worker.mjs"),
    "--workspace-root", workspaceRoot,
  ];
  const serverId = forwardedOption(forwarded, "--server-id");
  if (wrapper.directory && serverId) {
    args.push("--server-directory", resolve(wrapper.directory), "--server-id", serverId);
  }
  return spawn(process.execPath, args, { cwd: workspaceRoot, env, stdio: "inherit" });
}

function forwardedOption(arguments_, name) {
  for (let index = 0; index < arguments_.length; index += 1) {
    if (arguments_[index] === name) return arguments_[index + 1];
    if (arguments_[index].startsWith(`${name}=`)) return arguments_[index].slice(name.length + 1);
  }
  return undefined;
}

function parseWrapperArguments(arguments_) {
  const mode = arguments_[0] || "server";
  if (mode !== "server" && mode !== "client" && mode !== "gateway") throw new Error("mode must be server, client, or gateway");
  const wrapper = { sourceRoot: undefined, directory: undefined, workspace: undefined };
  const forwarded = [];
  for (let index = 1; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    const match = /^--(source-root|directory|workspace)=(.*)$/u.exec(argument);
    if (match) {
      const key = match[1] === "source-root" ? "sourceRoot" : match[1];
      if (!match[2] || wrapper[key] !== undefined) throw new Error(`--${match[1]} requires one value`);
      wrapper[key] = match[2];
      continue;
    }
    if (["--source-root", "--directory", "--workspace"].includes(argument)) {
      const key = argument === "--source-root" ? "sourceRoot" : argument.slice(2);
      const value = arguments_[++index];
      if (!value || wrapper[key] !== undefined) throw new Error(`${argument} requires one value`);
      wrapper[key] = value;
      continue;
    }
    forwarded.push(argument);
  }
  return { mode, wrapper, forwarded };
}
