import { execFileSync, spawn } from "node:child_process";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    "source-root": { type: "string" }, directory: { type: "string" }, workspace: { type: "string" },
    "session-dir": { type: "string" }, "server-id": { type: "string" },
    provider: { type: "string" }, model: { type: "string" },
    connect: { type: "string" }, "session-id": { type: "string" }, "allow-writes": { type: "boolean" },
    continue: { type: "boolean" }, resume: { type: "boolean" }, prompt: { type: "string" },
  },
});
const configuredRoot = values["source-root"] || process.env.TSPI_PI_SOURCE;
if (!configuredRoot) throw new Error("Pi source is required; set TSPI_PI_SOURCE or pass --source-root");
const sourceRoot = resolve(configuredRoot);
if (!existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/cli.ts"))) {
  throw new Error(`Pi source does not contain the experimental CLI: ${sourceRoot}`);
}
const pinPath = join(dirname(fileURLToPath(import.meta.url)), "../../config/pi-source.json");
const pin = JSON.parse(readFileSync(pinPath, "utf8"));
const commit = execFileSync("git", ["-C", sourceRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (commit !== pin.commit) throw new Error(`Pi source commit mismatch: expected ${pin.commit}, found ${commit}`);
const processSource = join(sourceRoot, "packages/coding-agent/src/experimental/process.ts");
if (!readFileSync(processSource, "utf8").includes("PI_SESSION_WORKER_ENTRY")) {
  throw new Error("Pi source is missing the TSPi Worker entrypoint patch; run prepare_pi_source.py --apply-worker-patch");
}
const mode = positionals[0] || "server";
if (mode !== "server" && mode !== "client") throw new Error("mode must be server or client");
if (positionals.length > 1) throw new Error("only one app-server mode is allowed: server or client");
const incompatible = mode === "server"
  ? ["connect", "session-id", "continue", "resume", "prompt"]
  : ["workspace", "session-dir", "server-id", "allow-writes"];
for (const name of incompatible) {
  if (values[name] !== undefined) throw new Error(`--${name} is not valid in ${mode} mode`);
}
const args = [join(sourceRoot, "packages/coding-agent/src/experimental/cli.ts"), mode];
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const workspaceRoot = values.workspace ? resolve(values.workspace) : undefined;
if (workspaceRoot) {
  if (!existsSync(workspaceRoot)) throw new Error(`TSPi workspace does not exist: ${workspaceRoot}`);
  const workspaceStat = lstatSync(workspaceRoot);
  if (!workspaceStat.isDirectory() || workspaceStat.isSymbolicLink()) {
    throw new Error(`TSPi workspace must be a regular directory: ${workspaceRoot}`);
  }
}
if (mode === "server" && !workspaceRoot) throw new Error("native TSPi server requires --workspace");
const childEnv = {
  ...process.env,
  PI_EXPERIMENTAL: "1",
  TSPI_PI_SOURCE: sourceRoot,
  TSPI_PACKAGE_ROOT: process.env.TSPI_PACKAGE_ROOT || packageRoot,
  PI_SESSION_WORKER_ENTRY: join(packageRoot, "apps/host/pi-session-worker.mjs"),
};
if (values["allow-writes"]) childEnv.TSPI_NATIVE_WRITES = "1";
else delete childEnv.TSPI_NATIVE_WRITES;
if (values.directory) childEnv.PI_SERVER_DIR = resolve(values.directory);
if (mode === "server") {
  if (values["session-dir"]) args.push("--session-dir", resolve(values["session-dir"]));
  if (values["server-id"]) args.push("--server-id", values["server-id"]);
  if (values.provider) args.push("--provider", values.provider);
  if (values.model) args.push("--model", values.model);
} else {
  if (values.connect) args.push("--connect", values.connect);
  if (values["session-id"]) args.push("--session-id", values["session-id"]);
  if (values.continue) args.push("--continue");
  if (values.resume) args.push("--resume");
  if (values.provider) args.push("--provider", values.provider);
  if (values.model) args.push("--model", values.model);
  if (values.prompt) args.push("--", values.prompt);
}
const child = spawn(process.execPath, ["--import", join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts"), ...args], {
  cwd: workspaceRoot || sourceRoot, env: childEnv, stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"]) process.once(signal, () => child.kill(signal));
child.once("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
