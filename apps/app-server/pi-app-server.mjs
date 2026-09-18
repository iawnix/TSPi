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
const commit = execFileSync("git", ["-C", sourceRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (commit !== pin.commit) throw new Error(`Pi source commit mismatch: expected ${pin.commit}, found ${commit}`);
const processSource = join(sourceRoot, "packages/coding-agent/src/experimental/process.ts");
if (!readFileSync(processSource, "utf8").includes("PI_SESSION_WORKER_ENTRY")) {
  throw new Error("Pi source is missing the TSPi Worker entrypoint patch; run prepare_pi_source.py --apply-worker-patch");
}
const args = [join(sourceRoot, "packages/coding-agent/src/experimental/cli.ts"), mode, ...forwarded];
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
  cwd: workspaceRoot || sourceRoot, env: childEnv, stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => child.kill(signal));
child.once("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));

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
