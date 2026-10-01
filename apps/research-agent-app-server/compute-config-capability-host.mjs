import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";

const executeFile = promisify(execFile);
const BRIDGE_SCHEMA = "research_agent_compute_bridge/1";
const READINESS_SCHEMA = "compute_readiness_1";

export class ComputeConfigCapabilityHostError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "ComputeConfigCapabilityHostError";
    this.code = code;
    this.details = details;
  }
}

/**
 * Load the Native Python capability catalog and installation environment
 * bindings. This boundary is descriptive only: it never imports or constructs
 * a JavaScript provider, gateway, or orchestrator. Actual execution always
 * goes through ts_compute.py and the Native lifecycle.
 */
export async function create_compute_config_capability_host({
  config_path,
  package_root,
  python = process.env.TS_AGENT_PYTHON || "python3",
  bridge_script,
} = {}) {
  if (typeof config_path !== "string" || config_path.length === 0) {
    throw new ComputeConfigCapabilityHostError("compute_config_required", "compute.toml path is required");
  }
  const packageRoot = resolve(package_root || process.cwd());
  const script = resolve(bridge_script || `${packageRoot}/scripts/research_agent_capability_bridge.py`);
  let completed;
  try {
    completed = await executeFile(python, [script, "--config", resolve(config_path)], {
      cwd: packageRoot,
      env: { ...process.env, TSPI_PACKAGE_ROOT: packageRoot, PYTHONNOUSERSITE: "1" },
      timeout: 30_000,
      maxBuffer: 2 * 1024 * 1024,
    });
  } catch (error) {
    throw new ComputeConfigCapabilityHostError("compute_config_bridge_failed", "could not load compute.toml Native capability catalog", {
      cause: String(error?.stderr || error?.message || error),
    });
  }
  let document;
  try {
    document = JSON.parse(completed.stdout);
  } catch (error) {
    throw new ComputeConfigCapabilityHostError("compute_config_bridge_invalid", "Native capability bridge returned invalid JSON", {
      cause: String(error?.message || error),
    });
  }
  if (!document || document.schema_version !== BRIDGE_SCHEMA || document.ok !== true
      || !Array.isArray(document.capabilities) || !document.bindings) {
    throw new ComputeConfigCapabilityHostError(
      "compute_config_invalid",
      document?.error || "Native capability catalog is unavailable",
      { bridge: document },
    );
  }
  const capabilities = Object.freeze(document.capabilities.map((item) => Object.freeze({ ...item })));
  const bindings = Object.freeze({ ...document.bindings });
  async function readiness({ capability_id, environment_id, execution_kind } = {}) {
    for (const [field, value] of [["capability_id", capability_id], ["environment_id", environment_id]]) {
      if (value !== undefined && (typeof value !== "string" || value.length === 0 || value.includes("\0"))) {
        throw new TypeError(`${field} must be a non-empty string`);
      }
    }
    if (execution_kind !== undefined && execution_kind !== "local" && execution_kind !== "remote") {
      throw new TypeError("execution_kind must be local or remote");
    }
    const args = [
      `${packageRoot}/scripts/ts_api.py`,
      "compute.readiness",
      "--root",
      packageRoot,
    ];
    if (capability_id !== undefined) args.push("--capability-id", capability_id);
    if (environment_id !== undefined) args.push("--environment-id", environment_id);
    if (execution_kind !== undefined) args.push("--execution-kind", execution_kind);
    let result;
    try {
      const completed = await executeFile(python, args, {
        cwd: packageRoot,
        env: {
          ...process.env,
          TS_COMPUTE_CONFIG: resolve(config_path),
          TSPI_PACKAGE_ROOT: packageRoot,
          PYTHONNOUSERSITE: "1",
        },
        timeout: 60_000,
        maxBuffer: 8 * 1024 * 1024,
      });
      result = JSON.parse(completed.stdout);
    } catch (error) {
      throw new ComputeConfigCapabilityHostError("compute_readiness_failed", "Native compute readiness probe failed", {
        cause: String(error?.stderr || error?.message || error),
      });
    }
    if (!result || result.protocol_version !== READINESS_SCHEMA || !Array.isArray(result.readiness)) {
      throw new ComputeConfigCapabilityHostError("compute_readiness_invalid", "Native compute readiness returned an invalid response", {
        result,
      });
    }
    return Object.freeze(result.readiness.map((item) => Object.freeze({ ...item })));
  }
  return Object.freeze({
    protocol_version: "native_compute_capability_host_1",
    config_path: document.config_path,
    source: "compute.toml",
    catalog() { return capabilities; },
    list_capabilities() { return capabilities; },
    readiness,
    bindings,
    async close() {},
  });
}
