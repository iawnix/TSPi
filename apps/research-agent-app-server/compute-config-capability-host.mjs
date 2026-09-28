import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { resolve } from "node:path";

import { create_host_capability_assembly } from "./host-capability-assembly.mjs";
import {
  create_gaussian_provider,
  create_local_xyz_provider,
  create_pyscf_provider,
  create_tool_gateway,
  create_xtb_provider,
} from "../../packages/research-agent-capabilities/index.mjs";

const executeFile = promisify(execFile);
const BRIDGE_SCHEMA = "research_agent_compute_bridge/1";
const ADAPTERS = Object.freeze({
  xtb_local: create_xtb_provider,
  gaussian_local: create_gaussian_provider,
  pyscf_local: create_pyscf_provider,
});

export class ComputeConfigCapabilityHostError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "ComputeConfigCapabilityHostError";
    this.code = code;
    this.details = details;
  }
}

/**
 * Adapt the existing installation-owned compute.toml into the JS capability
 * plane.  The Python bridge is trusted Host code and its executable bindings
 * never cross the Agent-facing catalog.
 */
export async function create_compute_config_capability_host({
  config_path,
  package_root,
  artifact_root,
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
    throw new ComputeConfigCapabilityHostError("compute_config_bridge_failed", "could not load compute.toml capability bridge", {
      cause: String(error?.stderr || error?.message || error),
    });
  }
  let document;
  try {
    document = JSON.parse(completed.stdout);
  } catch (error) {
    throw new ComputeConfigCapabilityHostError("compute_config_bridge_invalid", "compute.toml capability bridge returned invalid JSON", {
      cause: String(error?.message || error),
    });
  }
  if (!document || document.schema_version !== BRIDGE_SCHEMA || document.ok !== true || !document.bindings) {
    throw new ComputeConfigCapabilityHostError(
      "compute_config_invalid",
      document?.error || "compute.toml capability bridge is unavailable",
      { bridge: document },
    );
  }

  const environment_broker = create_environment_broker(document.bindings);
  const gateway = create_tool_gateway({
    workspace_mode: undefined,
    artifact_root,
    environment_broker,
    providers: [create_local_xyz_provider({ environment_broker })],
  });
  const inventory = [];
  const allowlist = [];
  const adapters = {};
  for (const [adapter_id, factory] of Object.entries(ADAPTERS)) {
    const binding = document.bindings[adapter_id];
    if (!binding?.available) continue;
    const provider = factory({ artifact_store: gateway.artifact_store, environment_broker });
    const descriptors = provider.descriptors();
    if (!Array.isArray(descriptors) || descriptors.length === 0) {
      throw new ComputeConfigCapabilityHostError("provider_invalid", `trusted adapter ${adapter_id} returned an invalid descriptor set`);
    }
    const manifest_provider_id = adapter_id === "xtb_local" ? "xtb" : adapter_id === "gaussian_local" ? "gaussian" : "pyscf";
    inventory.push({
      id: manifest_provider_id,
      version: "1",
      kind: "compute",
    });
    allowlist.push({
      manifest_provider_id,
      adapter_id,
      kind: "compute",
      version: "1",
      capability_ids: descriptors.map((descriptor) => descriptor.capability_id),
      required_tool_ids: [binding.backend],
    });
    adapters[adapter_id] = factory;
  }
  if (allowlist.length === 0) {
    throw new ComputeConfigCapabilityHostError("compute_capability_unavailable", "compute.toml does not configure a supported local compute backend");
  }
  const capability_assembly = create_host_capability_assembly({
    inventory,
    allowlist,
    adapters,
    artifact_store: gateway.artifact_store,
    environment_broker,
  });
  for (const provider of capability_assembly.providers) gateway.register_provider(provider);
  return Object.freeze({
    config_path: document.config_path,
    source: "compute.toml",
    inventory: Object.freeze(inventory.map((item) => Object.freeze({ ...item }))),
    environment_broker,
    capability_assembly,
    tool_gateway: gateway,
    allowlist: Object.freeze(allowlist.map((item) => Object.freeze({ ...item }))),
  });
}

function create_environment_broker(bindings) {
  const values = Object.freeze({ ...bindings });
  const resolve_binding = async (requirement = {}) => {
    const provider_id = requirement.provider_id;
    const configured = values[provider_id];
    const requested_environment = requirement.environment_id
      ?? requirement.environment
      ?? requirement.name;
    const requested_kind = requirement.execution_kind;
    const environments = configured?.environments && typeof configured.environments === "object"
      ? configured.environments
      : {};
    const by_alias = requested_environment === undefined
      ? undefined
      : Object.values(environments).find((item) => item?.available
        && (item.environment_id === requested_environment
          || item.aliases?.includes?.(requested_environment)));
    let binding = requested_environment === undefined ? configured : by_alias;
    if (requested_environment === undefined && requested_kind !== undefined
      && binding?.environment_kind !== requested_kind) {
      const candidates = Object.values(environments).filter((item) => item?.available && item.environment_kind === requested_kind);
      if (candidates.length === 1) binding = candidates[0];
      else if (candidates.length > 1) {
        throw Object.assign(new Error(`multiple ${requested_kind} compute environments are configured; select one by environment`), {
          code: "environment_unavailable",
          details: { environments: candidates.map((item) => item.environment_id) },
        });
      }
    }
    if (!binding?.available) {
      const backend = binding?.backend || provider_id;
      const suffix = requested_environment === undefined ? "" : ` in environment ${requested_environment}`;
      const available = Object.values(environments)
        .filter((item) => item?.available)
        .map((item) => item.environment_id)
        .filter(Boolean);
      throw Object.assign(new Error(`compute environment does not configure backend: ${backend}${suffix}`), {
        code: "environment_unavailable",
        details: { requested_environment, requested_kind, available_environments: available },
      });
    }
    if (requirement.environment_kind && requirement.environment_kind !== "compute") {
      throw Object.assign(new Error("compute capability requires a compute environment"), { code: "environment_unavailable" });
    }
    if (requested_kind !== undefined && requested_kind !== binding.environment_kind) {
      throw Object.assign(new Error(`compute environment kind is not available: ${requested_kind}`), {
        code: "environment_unavailable",
        details: { environment_id: binding.environment_id, requested_kind },
      });
    }
    return {
      schema_version: "research-agent-environment-binding/1",
      capability_id: requirement.capability_id,
      provider_id,
      environment_id: binding.environment_id,
      environment_kind: "compute",
      execution_kind: binding.environment_kind,
      command: binding.command,
      env: binding.environment || {},
      binding_digest: binding.binding_digest,
      readiness: binding.readiness,
    };
  };
  return Object.freeze({ protocol_version: "environment_broker_1", resolve: resolve_binding, bind: resolve_binding });
}
