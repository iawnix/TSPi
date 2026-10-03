/**
 * Host-owned Research State factory.
 *
 * A Research State module is loaded once by the App Server, while workspaces are
 * selected by individual requests.  This factory therefore returns a
 * workspace-aware ResearchStatePort that validates each research manifest
 * before binding the canonical Python Research State filesystem boundary bridge for that root.
 */

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { create_research_state_port } from "./ports.mjs";
import { create_python_kernel_bridge } from "./python_kernel_bridge.mjs";
import { validate_workspace_files } from "../agent-core/workspace.mjs";

export const RESEARCH_KERNEL_FACTORY_VERSION = "research_state_factory_1";
// The Research State filesystem boundary is implemented by the Python workspace
// boundary.  Node owns transport and port validation only; it must not carry
// a second state-machine implementation.
export const RESEARCH_KERNEL_BACKENDS = Object.freeze(["python"]);

const WORKSPACE_MANIFEST_SCHEMA = "research_state_workspace_1";
const WORKSPACE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;

function require_object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value;
}

function require_workspace_root(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("workspace_root is required");
  }
  return resolve(value);
}

function require_workspace_id(value, field = "workspace_id") {
  if (typeof value !== "string" || !WORKSPACE_ID.test(value)) {
    throw new TypeError(`${field} must be a non-empty identifier`);
  }
  return value;
}

function parse_options(value) {
  if (value === undefined || value === null) return {};
  if (typeof value === "string") {
    let parsed;
    try {
      parsed = JSON.parse(value);
    } catch (error) {
      throw new TypeError("kernel_options must be valid JSON", { cause: error });
    }
    return require_object(parsed, "kernel_options");
  }
  return require_object(value, "kernel_options");
}

function backend_name(value) {
  const normalized = value === undefined || value === null ? "python" : value;
  if (!RESEARCH_KERNEL_BACKENDS.includes(normalized)) {
    throw new TypeError(`unsupported Research State backend: ${String(value)}`);
  }
  return normalized;
}

async function read_manifest(root) {
  let manifest;
  try {
    manifest = JSON.parse(await readFile(resolve(root, "workspace_manifest.json"), "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error("workspace_manifest_missing", { cause: error });
    throw new Error("workspace_manifest_invalid", { cause: error });
  }
  require_object(manifest, "workspace manifest");
  await validate_workspace_files(manifest, root);
  const workspace_id = require_workspace_id(manifest.workspace_id, "workspace_id");
  if (manifest.workspace_mode !== "research") throw new Error("research_workspace_required");
  return manifest;
}

function request_binding(request, configured_root, configured_id) {
  const value = request === undefined || request === null ? {} : require_object(request, "kernel request");
  const requested_root = value.workspace_root ?? value.root ?? configured_root;
  if (requested_root === undefined) throw new Error("kernel_workspace_required");
  const workspace_root = require_workspace_root(requested_root);
  if (configured_root !== undefined && workspace_root !== configured_root) {
    throw new Error("research_workspace_root_mismatch");
  }
  const requested_id = value.workspace_id ?? configured_id;
  if (requested_id !== undefined) require_workspace_id(requested_id);
  if (configured_id !== undefined && requested_id !== undefined && requested_id !== configured_id) {
    throw new Error("research_workspace_id_mismatch");
  }
  return { value, workspace_root, workspace_id: requested_id };
}

function adapter_options(options) {
  const value = { ...options };
  for (const key of ["backend", "kind", "workspace_root", "workspace_id", "kernel_options"]) delete value[key];
  return value;
}

/**
 * Create a Research State Port suitable for `RESEARCH_AGENT_KERNEL_MODULE`.
 *
 * `workspace_root`/`workspace_id` may be supplied for a single-workspace
 * deployment.  When omitted, every request must provide `workspace_root` and
 * the factory routes it to a cached backend after validating the manifest.
 */
export function create_kernel(options = {}) {
  const outer = require_object(options, "kernel options");
  const parsed_options = parse_options(outer.kernel_options ?? outer);
  const parsed = outer.kernel_options === undefined
    ? parsed_options
    : {
      ...parsed_options,
      ...Object.fromEntries(Object.entries(outer).filter(([key]) => key !== "kernel_options")),
    };
  const backend = backend_name(parsed.backend ?? parsed.kind);
  const configured_root = parsed.workspace_root === undefined
    ? undefined
    : require_workspace_root(parsed.workspace_root);
  const configured_id = parsed.workspace_id === undefined
    ? undefined
    : require_workspace_id(parsed.workspace_id);
  const backend_config = adapter_options(parsed);
  const adapters = new Map();
  const roots_by_id = new Map();
  let closed = false;

  async function bind(request = {}) {
    if (closed) throw new Error("research_state_closed");
    const requested = request === undefined || request === null ? {} : require_object(request, "kernel request");
    const cached_root = requested.workspace_root === undefined && requested.root === undefined
      && requested.workspace_id !== undefined
      ? roots_by_id.get(requested.workspace_id)
      : undefined;
    const binding = request_binding(
      cached_root === undefined ? requested : { ...requested, workspace_root: cached_root },
      configured_root,
      configured_id,
    );
    const manifest = await read_manifest(binding.workspace_root);
    if (binding.workspace_id !== undefined && binding.workspace_id !== manifest.workspace_id) {
      throw new Error("research_workspace_id_mismatch");
    }
    const known_root = roots_by_id.get(manifest.workspace_id);
    if (known_root !== undefined && known_root !== binding.workspace_root) {
      throw new Error("research_workspace_id_mismatch");
    }
    roots_by_id.set(manifest.workspace_id, binding.workspace_root);
    let adapter = adapters.get(binding.workspace_root);
    if (!adapter) {
      const options_for_adapter = {
        ...backend_config,
        workspace_root: binding.workspace_root,
        workspace_id: manifest.workspace_id,
      };
      adapter = create_python_kernel_bridge(options_for_adapter);
      adapters.set(binding.workspace_root, adapter);
    }
    return {
      adapter,
      request: {
        ...binding.value,
        workspace_root: binding.workspace_root,
        workspace_id: manifest.workspace_id,
      },
    };
  }

  const implementation = {
    async read_context(request = {}) {
      const bound = await bind(request);
      return bound.adapter.read_context(bound.request);
    },
    async read_liveness(request = {}) {
      const bound = await bind(request);
      return bound.adapter.read_liveness(bound.request);
    },
    async admit_workspace(request = {}) {
      const bound = await bind(request);
      return bound.adapter.admit_workspace(bound.request);
    },
    async apply_change(request = {}) {
      const bound = await bind(request);
      return bound.adapter.apply_change(bound.request);
    },
    async checkpoint(request = {}) {
      const bound = await bind(request);
      return bound.adapter.checkpoint(bound.request);
    },
    async turn(request = {}) {
      const bound = await bind(request);
      return bound.adapter.turn(bound.request);
    },
  };
  const port = create_research_state_port(implementation);
  return Object.freeze({
    ...port,
    protocol_version: RESEARCH_KERNEL_FACTORY_VERSION,
    backend,
    ...(configured_root === undefined ? {} : { workspace_root: configured_root }),
    ...(configured_id === undefined ? {} : { workspace_id: configured_id }),
    async close() {
      if (closed) return;
      closed = true;
      await Promise.all([...adapters.values()].map((adapter) => (
        typeof adapter.close === "function" ? adapter.close() : undefined
      )));
      adapters.clear();
      roots_by_id.clear();
    },
  });
}
