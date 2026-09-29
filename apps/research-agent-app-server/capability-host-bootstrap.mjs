import { lstat, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { discoverInstalledExtensions } from "../../apps/app-server/extension-manifest-loader.mjs";
import { create_host_capability_assembly } from "./host-capability-assembly.mjs";
import {
  create_gaussian_provider,
  create_local_xyz_provider,
  create_pyscf_provider,
  create_crest_provider,
  create_tool_gateway,
  create_xtb_provider,
} from "../../packages/research-agent-capabilities/index.mjs";
import { create_compute_config_capability_host } from "./compute-config-capability-host.mjs";

export const CAPABILITY_HOST_CONFIG_SCHEMA = "research_agent_capabilities/1";

const TRUSTED_ADAPTERS = Object.freeze({
  local_geometry: create_local_xyz_provider,
  xtb_local: create_xtb_provider,
  gaussian_local: create_gaussian_provider,
  pyscf_local: create_pyscf_provider,
  crest_local: create_crest_provider,
});

export class CapabilityHostBootstrapError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "CapabilityHostBootstrapError";
    this.code = code;
    this.details = details;
  }
}

function fail(code, message, details = {}) {
  throw new CapabilityHostBootstrapError(code, message, details);
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("invalid_capability_config", `${field} must be an object`);
  return value;
}

function config_path(value) {
  if (typeof value !== "string" || value.length === 0) return null;
  const trimmed = value.trim();
  if (!trimmed.startsWith("/")) {
    fail("invalid_capability_config", "capability and compute config paths must be absolute");
  }
  return resolve(trimmed);
}

/**
 * Resolve the installation-owned compute profile the same way as the Python
 * launcher.  App Server workers inherit the environment in normal service
 * startup, but direct worker/server launches do not necessarily run the
 * launcher validation step first.  Keeping this fallback here makes the
 * config chain deterministic without allowing a relative or arbitrary path.
 */
async function default_compute_config_path(explicit) {
  const selected = config_path(explicit || process.env.TS_COMPUTE_CONFIG);
  if (selected) return selected;
  const install_root = config_path(process.env.TSPI_INSTALL_ROOT);
  if (!install_root) return null;
  const candidate = join(install_root, ".pi", "compute.toml");
  try {
    const info = await lstat(candidate);
    if (!info.isFile() || info.isSymbolicLink()) return null;
    return candidate;
  } catch {
    return null;
  }
}

async function read_config(path) {
  if (!path) return null;
  let value;
  try {
    value = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    fail("capability_config_unavailable", `could not read capability config: ${path}`, { cause: String(error?.message || error) });
  }
  object(value, "capability config");
  if (value.schema_version !== CAPABILITY_HOST_CONFIG_SCHEMA) {
    fail("invalid_capability_config", `capability config schema_version must be ${CAPABILITY_HOST_CONFIG_SCHEMA}`);
  }
  return value;
}

function module_specifier(value, package_root, field) {
  if (typeof value !== "string" || value.trim().length === 0) fail("environment_broker_not_configured", `${field} must be a non-empty module specifier`);
  const trimmed = value.trim();
  if (trimmed.startsWith("file:") || (!trimmed.startsWith(".") && !trimmed.startsWith("/"))) return trimmed;
  return pathToFileURL(resolve(package_root, trimmed)).href;
}

async function load_environment_broker(config, package_root, options) {
  const specifier = module_specifier(config.environment_module, package_root, "environment_module");
  let module;
  try {
    module = await import(specifier);
  } catch (error) {
    fail("environment_broker_unavailable", `could not import EnvironmentBroker module: ${specifier}`, { cause: String(error?.message || error) });
  }
  if (typeof module.create_environment_broker !== "function") {
    fail("environment_broker_invalid", "EnvironmentBroker module must export create_environment_broker()");
  }
  let broker;
  try {
    broker = await module.create_environment_broker(Object.freeze({
      package_root,
      artifact_root: options.artifact_root,
      config: Object.freeze({ ...config }),
    }));
  } catch (error) {
    fail("environment_broker_unavailable", "EnvironmentBroker factory failed", { cause: String(error?.message || error) });
  }
  if (!broker || typeof broker !== "object" || Array.isArray(broker)
      || (typeof broker.resolve !== "function" && typeof broker.bind !== "function")) {
    fail("environment_broker_invalid", "EnvironmentBroker must expose resolve() or bind()");
  }
  return broker;
}

function inventory_from_discovery(discovery) {
  return discovery.providers.map((provider) => ({
    id: provider.id,
    version: provider.version,
    kind: provider.kind,
    ...(provider.descriptor_digest === undefined ? {} : { descriptor_digest: provider.descriptor_digest }),
    ...(provider.descriptor_data === undefined ? {} : { descriptor_data: provider.descriptor_data }),
    ...(provider.entry === undefined ? {} : { entry: provider.entry }),
  }));
}

function trusted_adapters(config) {
  const requested = config.adapters;
  if (requested === undefined) return TRUSTED_ADAPTERS;
  if (!Array.isArray(requested) || requested.some((value) => typeof value !== "string" || value.length === 0)) {
    fail("invalid_capability_config", "adapters must be an array of trusted adapter ids");
  }
  const result = {};
  for (const id of requested) {
    if (!Object.hasOwn(TRUSTED_ADAPTERS, id)) fail("adapter_not_trusted", `trusted adapter is not registered: ${id}`);
    result[id] = TRUSTED_ADAPTERS[id];
  }
  return result;
}

/**
 * Build the Host-owned capability boundary for the standalone server.
 * An absent config is intentionally a no-op. A present config must name an
 * EnvironmentBroker module and an allowlist; manifests are inventory only,
 * while executable adapters come exclusively from TRUSTED_ADAPTERS above.
 */
export async function create_configured_capability_host({
  config_path: configured_path,
  compute_config_path,
  package_root = resolve(new URL("../..", import.meta.url).pathname),
  artifact_root,
} = {}) {
  const path = config_path(configured_path);
  const config = await read_config(path);
  if (config === null) {
    const computePath = await default_compute_config_path(compute_config_path);
    if (!computePath) return null;
    return create_compute_config_capability_host({
      config_path: computePath,
      package_root,
      artifact_root,
    });
  }
  if (!Array.isArray(config.allowlist)) fail("invalid_capability_config", "allowlist must be an array");
  const manifest_paths = config.manifest_paths;
  if (manifest_paths !== undefined && (!Array.isArray(manifest_paths) || manifest_paths.some((value) => typeof value !== "string" || value.length === 0))) {
    fail("invalid_capability_config", "manifest_paths must be an array of absolute paths");
  }
  const discovery = await discoverInstalledExtensions({
    packageRoot: package_root,
    ...(manifest_paths === undefined ? {} : { manifestPaths: manifest_paths }),
  });
  const environment_broker = await load_environment_broker(config, package_root, { artifact_root });
  const gateway = create_tool_gateway({ artifact_root, environment_broker });
  const inventory = inventory_from_discovery(discovery);
  const assembly = create_host_capability_assembly({
    inventory,
    allowlist: config.allowlist,
    adapters: trusted_adapters(config),
    artifact_store: gateway.artifact_store,
    environment_broker,
  });
  for (const provider of assembly.providers) gateway.register_provider(provider);
  return Object.freeze({
    config_path: path,
    inventory: Object.freeze(inventory),
    environment_broker,
    capability_assembly: assembly,
    tool_gateway: gateway,
  });
}

export { TRUSTED_ADAPTERS };
