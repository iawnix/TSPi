import { lstat } from "node:fs/promises";
import { join, resolve } from "node:path";

import { create_compute_config_capability_host } from "./compute-config-capability-host.mjs";

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

function absolute_config_path(value) {
  if (typeof value !== "string" || value.length === 0) return null;
  const trimmed = value.trim();
  if (!trimmed.startsWith("/")) fail("invalid_compute_config", "compute config paths must be absolute");
  return resolve(trimmed);
}

async function default_compute_config_path(explicit) {
  const selected = absolute_config_path(explicit || process.env.TS_COMPUTE_CONFIG);
  if (selected) return selected;
  const install_root = absolute_config_path(process.env.TSPI_INSTALL_ROOT);
  if (!install_root) return null;
  const candidate = join(install_root, ".pi", "compute.toml");
  try {
    const info = await lstat(candidate);
    return info.isFile() && !info.isSymbolicLink() ? candidate : null;
  } catch {
    return null;
  }
}

/**
 * Build the Native-only capability catalog boundary. Provider adapters and
 * provider allowlists are intentionally unsupported; ts_compute owns the
 * descriptor registry and execution implementation.
 */
export async function create_configured_capability_host(options = {}) {
  if (options === null || typeof options !== "object" || Array.isArray(options)) {
    throw new TypeError("capability host options must be an object");
  }
  if (Object.hasOwn(options, "config_path")) {
    fail("js_provider_path_removed", "The legacy capability config was removed; use compute_config_path for Native compute.toml");
  }
  const {
    compute_config_path,
    package_root = resolve(new URL("../..", import.meta.url).pathname),
  } = options;
  const path = await default_compute_config_path(compute_config_path);
  if (!path) return null;
  return create_compute_config_capability_host({ config_path: path, package_root });
}
