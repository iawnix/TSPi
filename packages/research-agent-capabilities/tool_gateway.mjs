import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import { create_tool_gateway as create_tool_gateway_port } from "../research-agent-core/ports.mjs";
import { assert_workspace_mode } from "../research-agent-core/session_mode.mjs";

const PROVIDER_ID = "core_local";
const PROVIDER_VERSION = "1";
const MAX_ARTIFACT_BYTES = 8 * 1024 * 1024;
const MAX_XYZ_ATOMS = 100_000;
const PROVIDER_ID_PATTERN = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u;
const CAPABILITY_ID_PATTERN = /^[a-z][a-z0-9_]{0,127}$/u;
const CAPABILITY_VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/u;
const CAPABILITY_KINDS = new Set(["compute", "analysis", "artifact", "notification"]);
const WORKSPACE_MODE_VALUES = new Set(["light", "research"]);

export const CAPABILITY_TOOL_PROVIDER_ID = PROVIDER_ID;

export class CapabilityToolError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "CapabilityToolError";
    this.code = code;
    this.details = details;
  }
}

function canonical_json(value) {
  if (Array.isArray(value)) return value.map(canonical_json);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical_json(value[key])]));
  }
  return value;
}

function immutable_json(value) {
  if (Array.isArray(value)) return Object.freeze(value.map(immutable_json));
  if (value && typeof value === "object") {
    return Object.freeze(Object.fromEntries(Object.entries(value).map(([key, item]) => [key, immutable_json(item)])));
  }
  return value;
}

function digest_bytes(value) {
  return createHash("sha256").update(value).digest("hex");
}

function descriptor_digest_for(value) {
  const base = {
    ...value,
    provider: { ...value.provider },
  };
  delete base.provider.descriptor_digest;
  return "sha256:" + digest_bytes(Buffer.from(JSON.stringify(canonical_json(base))));
}

function descriptor({ capability_id, kind, summary, input_schema, output_schema, supported_workspace_modes = ["light", "research"] }) {
  const base = {
    protocol: "capability_descriptor",
    version: 1,
    capability_id,
    capability_version: "1",
    kind,
    summary,
    input_schema,
    output_schema,
    supported_workspace_modes,
    provider: {
      provider_id: PROVIDER_ID,
      provider_version: PROVIDER_VERSION,
    },
  };
  const descriptor_digest = descriptor_digest_for(base);
  return Object.freeze({
    ...base,
    provider: Object.freeze({ ...base.provider, descriptor_digest }),
  });
}

const DESCRIPTORS = Object.freeze([
  descriptor({
    capability_id: "artifact_create",
    kind: "artifact",
    summary: "Create an immutable content-addressed artifact from bounded bytes.",
    input_schema: {
      type: "object",
      required: ["content"],
      properties: {
        content: { type: "string", maxLength: MAX_ARTIFACT_BYTES },
        artifact_type: { type: "string", minLength: 1, maxLength: 128 },
        logical_ref: { type: "string", pattern: "^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$" },
        metadata: { type: "object" },
      },
      additionalProperties: false,
    },
    output_schema: { type: "object", required: ["artifact"] },
  }),
  descriptor({
    capability_id: "artifact_validate",
    kind: "analysis",
    summary: "Verify an immutable artifact digest and manifest.",
    input_schema: {
      type: "object",
      required: ["artifact_id"],
      properties: { artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" } },
      additionalProperties: false,
    },
    output_schema: { type: "object", required: ["valid", "artifact_id"] },
  }),
  descriptor({
    capability_id: "xyz_atom_count",
    kind: "analysis",
    summary: "Count atoms and element symbols in a validated XYZ structure.",
    supported_workspace_modes: ["research"],
    input_schema: {
      type: "object",
      properties: {
        xyz: { type: "string", maxLength: MAX_ARTIFACT_BYTES },
        artifact_id: { type: "string", pattern: "^art_[0-9a-f]{64}$" },
      },
      additionalProperties: false,
    },
    output_schema: { type: "object", required: ["atom_count", "elements"] },
  }),
]);

function capability_key(descriptor_value) {
  return descriptor_value.capability_id + "@" + descriptor_value.capability_version;
}

function provider_error(message, details = {}) {
  return new CapabilityToolError("invalid_provider", message, details);
}

/**
 * Normalize the executable-provider boundary. Providers are deliberately
 * objects supplied by the Host; they are never imported or selected by a
 * client request. A provider may advertise descriptors without exposing any
 * filesystem paths or command lines.
 */
function normalize_provider(provider) {
  if (!provider || typeof provider !== "object" || Array.isArray(provider)) {
    throw provider_error("provider must be an object");
  }
  const provider_id = provider.provider_id;
  if (typeof provider_id !== "string" || !PROVIDER_ID_PATTERN.test(provider_id)) {
    throw provider_error("provider_id must be a lowercase snake_case identifier");
  }
  const provider_version = provider.provider_version === undefined ? "1" : provider.provider_version;
  if (typeof provider_version !== "string" || !CAPABILITY_VERSION_PATTERN.test(provider_version)) {
    throw provider_error("provider_version is invalid");
  }
  if (typeof provider.descriptors !== "function") throw provider_error("provider must expose descriptors()");
  if (typeof provider.invoke !== "function") throw provider_error("provider must expose invoke()");
  let values;
  try {
    values = Array.from(provider.descriptors());
  } catch (error) {
    throw provider_error("provider descriptors() failed", { cause: String(error?.message || error) });
  }
  if (values.length === 0) throw provider_error("provider must advertise at least one descriptor");
  const descriptors = values.map((value) => normalize_provider_descriptor(value, provider_id, provider_version));
  const keys = descriptors.map(capability_key);
  if (new Set(keys).size !== keys.length) throw provider_error("provider returned duplicate capability versions");
  return {
    provider,
    provider_id,
    provider_version,
    descriptors: Object.freeze(descriptors),
  };
}

function normalize_provider_descriptor(value, provider_id, provider_version) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw provider_error("provider descriptor must be an object");
  }
  if (value.protocol !== "capability_descriptor" || value.version !== 1) {
    throw provider_error("provider descriptor protocol is invalid");
  }
  if (value.protocol !== "capability_descriptor" || value.version !== 1) {
    throw provider_error("provider descriptor requires protocol=capability_descriptor and version=1");
  }
  const unknown_fields = Object.keys(value).filter((field) => !new Set([
    "protocol", "version", "capability_id", "capability_version", "kind", "summary",
    "input_schema", "output_schema", "supported_workspace_modes", "provider", "limits", "effects",
  ]).has(field));
  if (unknown_fields.length > 0) throw provider_error(`provider descriptor contains unknown field: ${unknown_fields[0]}`);
  const capability_id = value.capability_id;
  const capability_version = value.capability_version;
  if (typeof capability_id !== "string" || !CAPABILITY_ID_PATTERN.test(capability_id)) {
    throw provider_error("provider descriptor capability_id is invalid");
  }
  if (typeof capability_version !== "string" || !CAPABILITY_VERSION_PATTERN.test(capability_version)) {
    throw provider_error("provider descriptor capability_version is invalid");
  }
  if (!CAPABILITY_KINDS.has(value.kind)) throw provider_error("provider descriptor kind is invalid");
  if (typeof value.summary !== "string" || value.summary.length === 0 || value.summary.length > 2000) {
    throw provider_error("provider descriptor summary is invalid");
  }
  for (const field of ["input_schema", "output_schema"]) {
    if (!value[field] || typeof value[field] !== "object" || Array.isArray(value[field])) {
      throw provider_error(`provider descriptor ${field} must be an object`);
    }
  }
  if (!Array.isArray(value.supported_workspace_modes) || value.supported_workspace_modes.length === 0
      || value.supported_workspace_modes.some((mode) => !WORKSPACE_MODE_VALUES.has(mode))
      || new Set(value.supported_workspace_modes).size !== value.supported_workspace_modes.length) {
    throw provider_error("provider descriptor supported_workspace_modes is invalid");
  }
  if (value.limits !== undefined && (!value.limits || typeof value.limits !== "object" || Array.isArray(value.limits)
      || Object.keys(value.limits).length > 64)) {
    throw provider_error("provider descriptor limits is invalid");
  }
  if (value.effects !== undefined && (!Array.isArray(value.effects) || value.effects.length > 32
      || value.effects.some((effect) => typeof effect !== "string" || !/^[a-z][a-z0-9_]{0,63}$/u.test(effect))
      || new Set(value.effects).size !== value.effects.length)) {
    throw provider_error("provider descriptor effects is invalid");
  }
  const advertised_provider = value.provider;
  if (advertised_provider !== undefined && (!advertised_provider || typeof advertised_provider !== "object" || Array.isArray(advertised_provider))) {
    throw provider_error("provider descriptor provider must be an object");
  }
  if (advertised_provider?.provider_id !== undefined && advertised_provider.provider_id !== provider_id) {
    throw provider_error("provider descriptor provider_id does not match provider");
  }
  if (advertised_provider?.provider_version !== undefined && advertised_provider.provider_version !== provider_version) {
    throw provider_error("provider descriptor provider_version does not match provider");
  }
  if (advertised_provider) {
    const unknown_provider_fields = Object.keys(advertised_provider)
      .filter((field) => !new Set(["provider_id", "provider_version", "descriptor_digest"]).has(field));
    if (unknown_provider_fields.length > 0) {
      throw provider_error(`provider descriptor provider contains unknown field: ${unknown_provider_fields[0]}`);
    }
  }
  const base = {
    protocol: "capability_descriptor",
    version: 1,
    capability_id,
    capability_version,
    kind: value.kind,
    summary: value.summary,
    input_schema: value.input_schema,
    output_schema: value.output_schema,
    supported_workspace_modes: [...value.supported_workspace_modes],
    provider: { provider_id, provider_version },
    ...(value.limits === undefined ? {} : { limits: value.limits }),
    ...(value.effects === undefined ? {} : { effects: value.effects }),
  };
  let expected_digest;
  try {
    expected_digest = descriptor_digest_for(base);
  } catch (error) {
    throw provider_error("provider descriptor must be JSON serializable", { cause: String(error?.message || error) });
  }
  const supplied_digest = advertised_provider?.descriptor_digest;
  if (supplied_digest !== undefined && supplied_digest !== expected_digest) {
    throw provider_error("provider descriptor digest is invalid", { expected: expected_digest });
  }
  return Object.freeze({
    ...base,
    input_schema: immutable_json(base.input_schema),
    output_schema: immutable_json(base.output_schema),
    supported_workspace_modes: Object.freeze([...base.supported_workspace_modes]),
    ...(base.limits === undefined ? {} : { limits: immutable_json(base.limits) }),
    ...(base.effects === undefined ? {} : { effects: immutable_json(base.effects) }),
    provider: Object.freeze({ ...base.provider, descriptor_digest: expected_digest }),
  });
}

function require_object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new CapabilityToolError("invalid_input", field + " must be an object");
  }
  return value;
}

function require_string(value, field) {
  if (typeof value !== "string" || value.length === 0) {
    throw new CapabilityToolError("invalid_input", field + " must be a non-empty string");
  }
  return value;
}

function ensure_logical_ref(value) {
  const logical_ref = value || "artifacts/generated.bin";
  if (typeof logical_ref !== "string" || !/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/u.test(logical_ref)) {
    throw new CapabilityToolError("invalid_artifact_ref", "logical_ref must be a relative path");
  }
  if (logical_ref.split("/").some((segment) => segment === "." || segment === "..")) {
    throw new CapabilityToolError("invalid_artifact_ref", "logical_ref must not contain traversal segments");
  }
  return logical_ref;
}

function artifact_id_for(digest) {
  return "art_" + digest;
}

function digest_from_artifact_id(artifact_id) {
  if (typeof artifact_id !== "string" || !/^art_[0-9a-f]{64}$/u.test(artifact_id)) {
    throw new CapabilityToolError("invalid_artifact_id", "artifact_id is invalid");
  }
  return artifact_id.slice(4);
}

function bytes_from_content(content) {
  if (typeof content !== "string") throw new CapabilityToolError("invalid_input", "content must be a string");
  const bytes = Buffer.from(content, "utf8");
  if (bytes.byteLength > MAX_ARTIFACT_BYTES) {
    throw new CapabilityToolError("artifact_too_large", "artifact content exceeds the size limit");
  }
  return bytes;
}

function ensure_artifact_type(value) {
  const artifact_type = value === undefined ? "text/plain" : value;
  if (typeof artifact_type !== "string" || artifact_type.length === 0 || artifact_type.length > 128) {
    throw new CapabilityToolError("invalid_input", "artifact_type must be a non-empty string of at most 128 characters");
  }
  return artifact_type;
}

function ensure_metadata(value) {
  if (value === undefined) return undefined;
  require_object(value, "metadata");
  try {
    const encoded = JSON.stringify(canonical_json(value));
    if (encoded === undefined) throw new Error("metadata is not JSON serializable");
    return JSON.parse(encoded);
  } catch (error) {
    throw new CapabilityToolError("invalid_input", "metadata must be JSON serializable", {
      cause: String(error?.message || error),
    });
  }
}

async function ensure_store_root(root) {
  await mkdir(root, { recursive: true, mode: 0o700 });
  for (const directory of [root, join(root, "content"), join(root, "manifests")]) {
    await mkdir(directory, { recursive: true, mode: 0o700 });
    let info;
    try {
      info = await lstat(directory);
    } catch (error) {
      throw new CapabilityToolError("invalid_artifact_store", "artifact store directory is unavailable", {
        path: directory,
        cause: String(error?.message || error),
      });
    }
    if (info.isSymbolicLink() || !info.isDirectory()) {
      throw new CapabilityToolError("invalid_artifact_store", "artifact store paths must be directories, not symlinks", {
        path: directory,
      });
    }
  }
}

function parse_xyz(value) {
  if (typeof value !== "string") throw new CapabilityToolError("invalid_xyz", "xyz must be a string");
  const lines = value.replace(/\r\n?/gu, "\n").trimEnd().split("\n");
  if (lines.length < 2) throw new CapabilityToolError("invalid_xyz", "XYZ requires a count and comment line");
  const atom_count = Number.parseInt(lines[0].trim(), 10);
  if (!Number.isSafeInteger(atom_count) || atom_count < 1 || atom_count > MAX_XYZ_ATOMS || String(atom_count) !== lines[0].trim()) {
    throw new CapabilityToolError("invalid_xyz", "XYZ atom count is invalid");
  }
  if (lines.length !== atom_count + 2) throw new CapabilityToolError("invalid_xyz", "XYZ atom line count does not match the header");
  const elements = {};
  for (const line of lines.slice(2)) {
    const fields = line.trim().split(/\s+/u);
    if (fields.length < 4 || !/^[A-Z][a-z]?[0-9]*$/u.test(fields[0])) {
      throw new CapabilityToolError("invalid_xyz", "XYZ atom row is invalid");
    }
    const coordinates = fields.slice(1, 4).map(Number);
    if (coordinates.some((coordinate) => !Number.isFinite(coordinate))) {
      throw new CapabilityToolError("invalid_xyz", "XYZ coordinates must be finite");
    }
    elements[fields[0]] = (elements[fields[0]] || 0) + 1;
  }
  return { atom_count, elements };
}

/**
 * Bind one invocation to an Agent-selected environment identity while keeping
 * executable command details inside the Host EnvironmentBroker. The selector
 * is deliberately copied onto the broker requirement; it cannot replace or
 * inject a command/argv.
 */
function invocation_environment_broker(broker, request) {
  if (!broker || typeof broker !== "object") return broker;
  const target = request?.environment
    ?? request?.execution_environment
    ?? request?.execution_target
    ?? request?.executionTarget;
  if (target === undefined || target === null) return broker;
  const selector = typeof target === "string"
    ? { environment_id: target }
    : target && typeof target === "object" && !Array.isArray(target)
      ? {
          ...(target.environment_id === undefined && target.environment === undefined && target.name === undefined
            ? {}
            : { environment_id: target.environment_id ?? target.environment ?? target.name }),
          ...(target.kind === undefined ? {} : { execution_kind: target.kind }),
        }
      : null;
  if (!selector || (selector.environment_id === undefined && selector.execution_kind === undefined)) {
    throw new CapabilityToolError("invalid_environment_target", "environment target must identify an environment or execution kind");
  }
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") throw new CapabilityToolError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  const resolve_selected = async (requirement = {}) => resolver.call(broker, Object.freeze({
    ...requirement,
    ...selector,
    // Keep the public compute kind stable. `execution_kind` is the transport
    // selector (local/remote) consumed by environment-aware Hosts.
    environment_kind: requirement.environment_kind,
  }));
  return Object.freeze({ protocol_version: broker.protocol_version, resolve: resolve_selected, bind: resolve_selected });
}

export function create_tool_gateway({ workspace_mode, artifact_root, providers = [], artifact_store, environment_broker } = {}) {
  // An omitted mode creates a Host-level gateway that can serve either
  // workspace profile. Passing a mode keeps the gateway explicitly bound for
  // deployments that want an additional mode check at this boundary.
  const bound_workspace_mode = workspace_mode === undefined ? null : assert_workspace_mode(workspace_mode);
  if (!Array.isArray(providers)) throw new TypeError("providers must be an array");
  const memory = new Map();
  const root = artifact_root === undefined ? undefined : resolve(require_string(artifact_root, "artifact_root"));

  if (artifact_store !== undefined && (artifact_store === null || typeof artifact_store !== "object" || Array.isArray(artifact_store))) {
    throw new TypeError("artifact_store must be an object");
  }
  if (environment_broker !== undefined && (environment_broker === null || typeof environment_broker !== "object" || Array.isArray(environment_broker))) {
    throw new TypeError("environment_broker must be an object");
  }

  async function write_artifact(content, input) {
    const digest = digest_bytes(content);
    const artifact_id = artifact_id_for(digest);
    const artifact = {
      protocol: "artifact_manifest",
      version: 1,
      artifact_id,
      artifact_type: ensure_artifact_type(input.artifact_type),
      logical_ref: ensure_logical_ref(input.logical_ref),
      digest: "sha256:" + digest,
      size_bytes: content.byteLength,
      producer: {
        provider_id: PROVIDER_ID,
        provider_version: PROVIDER_VERSION,
        operation: "artifact_create",
        operation_version: "1",
      },
      provenance: {
        input_artifacts: [],
        created_at: new Date().toISOString(),
      },
    };
    const metadata = ensure_metadata(input.metadata);
    if (metadata !== undefined) artifact.metadata = metadata;
    if (root) {
      await ensure_store_root(root);
      const content_path = join(root, "content", digest + ".bin");
      const manifest_path = join(root, "manifests", digest + ".json");
      try {
        const existing = await readFile(content_path);
        if (!existing.equals(content)) throw new CapabilityToolError("artifact_collision", "artifact digest collision detected");
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
        await writeFile(content_path, content, { flag: "wx", mode: 0o600 });
      }
      await writeFile(manifest_path, JSON.stringify(artifact) + "\n", { flag: "wx", mode: 0o600 }).catch((error) => {
        if (error?.code !== "EEXIST") throw error;
      });
    }
    memory.set(artifact_id, { artifact, content: Buffer.from(content) });
    return artifact;
  }

  async function load_artifact(artifact_id) {
    const digest = digest_from_artifact_id(artifact_id);
    const cached = memory.get(artifact_id);
    if (cached) return cached;
    if (!root) throw new CapabilityToolError("artifact_not_found", "artifact is not present");
    const manifest_path = join(root, "manifests", digest + ".json");
    const content_path = join(root, "content", digest + ".bin");
    let artifact;
    let content;
    try {
      artifact = JSON.parse(await readFile(manifest_path, "utf8"));
      content = await readFile(content_path);
    } catch (error) {
      throw new CapabilityToolError("artifact_not_found", "artifact is not present", { cause: String(error?.message || error) });
    }
    const value = { artifact, content };
    memory.set(artifact_id, value);
    return value;
  }

  // Providers receive this narrow port instead of the gateway's private
  // filesystem state. The port is content-addressed and has no path or shell
  // operations, so a provider cannot escape the configured ArtifactStore.
  const provider_artifact_store = artifact_store ?? Object.freeze({
    create: async (input = {}) => write_artifact(bytes_from_content(input.content), input),
    read: async (artifact_id) => {
      const value = await load_artifact(artifact_id);
      return Object.freeze({ artifact: value.artifact, content: Buffer.from(value.content) });
    },
  });

  async function invoke_artifact_create(input) {
    const artifact = await write_artifact(bytes_from_content(input.content), input);
    return { output: { artifact }, artifacts: [artifact.artifact_id] };
  }

  async function invoke_artifact_validate(input) {
    const value = await load_artifact(require_string(input.artifact_id, "artifact_id"));
    const digest = digest_bytes(value.content);
    const valid = value.artifact.digest === "sha256:" + digest
      && value.artifact.artifact_id === artifact_id_for(digest)
      && value.artifact.size_bytes === value.content.byteLength;
    return {
      output: { valid, artifact_id: value.artifact.artifact_id, digest: value.artifact.digest, size_bytes: value.content.byteLength },
      artifacts: [value.artifact.artifact_id],
    };
  }

  async function invoke_xyz_atom_count(input) {
    let xyz = input.xyz;
    if (xyz === undefined && input.artifact_id !== undefined) {
      const value = await load_artifact(require_string(input.artifact_id, "artifact_id"));
      xyz = value.content.toString("utf8");
    }
    const parsed = parse_xyz(xyz);
    return { output: parsed, artifacts: input.artifact_id ? [input.artifact_id] : [] };
  }

  // The built-in implementation is itself a provider. Keeping it behind the
  // same registry as installed providers makes capability discovery a Host
  // concern and leaves this gateway independent of Skills or Pi.
  const builtin_provider = Object.freeze({
    provider_id: PROVIDER_ID,
    provider_version: PROVIDER_VERSION,
    descriptors: () => DESCRIPTORS,
    async invoke({ descriptor: item, input }) {
      if (item.capability_id === "artifact_create") return invoke_artifact_create(input);
      if (item.capability_id === "artifact_validate") return invoke_artifact_validate(input);
      if (item.capability_id === "xyz_atom_count") return invoke_xyz_atom_count(input);
      throw new CapabilityToolError("capability_not_implemented", "capability implementation is unavailable");
    },
  });

  const registrations = new Map();
  const provider_entries = new Map();

  function add_provider(provider, { replace = false } = {}) {
    const normalized = normalize_provider(provider);
    const previous_provider = provider_entries.get(normalized.provider_id);
    if (previous_provider && !replace) {
      throw new CapabilityToolError("provider_already_registered", "provider is already registered", {
        provider_id: normalized.provider_id,
      });
    }
    const previous_entries = previous_provider
      ? previous_provider.descriptors.map(capability_key)
      : [];
    const collisions = normalized.descriptors
      .map(capability_key)
      .filter((key) => registrations.has(key) && !previous_entries.includes(key));
    if (collisions.length > 0) {
      throw new CapabilityToolError("capability_already_registered", "capability version is already registered", {
        capability: collisions[0],
      });
    }
    // Validate the complete provider before mutating the live catalog. This
    // keeps a failed external registration from exposing a partial catalog.
    for (const key of previous_entries) registrations.delete(key);
    for (const item of normalized.descriptors) registrations.set(capability_key(item), { descriptor: item, provider: normalized.provider });
    provider_entries.set(normalized.provider_id, normalized);
    return normalized.descriptors;
  }

  function remove_provider(provider_id) {
    if (provider_id === PROVIDER_ID) {
      throw new CapabilityToolError("provider_protected", "the core provider cannot be removed");
    }
    const registered = provider_entries.get(provider_id);
    if (!registered) return false;
    for (const item of registered.descriptors) registrations.delete(capability_key(item));
    provider_entries.delete(provider_id);
    return true;
  }

  add_provider(builtin_provider);
  for (const provider of providers) add_provider(provider);

  const gateway = {
    protocol_version: "tool_gateway_1",
    register_provider(provider, options = {}) {
      return Object.freeze([...add_provider(provider, options)]);
    },
    unregister_provider(provider_id) {
      return remove_provider(provider_id);
    },
    list_providers() {
      return Object.freeze([...provider_entries.values()].map((entry) => Object.freeze({
        provider_id: entry.provider_id,
        provider_version: entry.provider_version,
        capabilities: Object.freeze(entry.descriptors.map((item) => Object.freeze({
          capability_id: item.capability_id,
          capability_version: item.capability_version,
        }))),
      })));
    },
    describe({ workspace_mode = bound_workspace_mode ?? "light" } = {}) {
      const mode = assert_workspace_mode(workspace_mode);
      if (bound_workspace_mode !== null && mode !== bound_workspace_mode) {
        throw new CapabilityToolError("workspace_mode_mismatch", "workspace mode does not match the gateway");
      }
      return [...registrations.values()]
        .map((entry) => entry.descriptor)
        .filter((item) => item.supported_workspace_modes.includes(mode));
    },
    async invoke(request) {
      require_object(request, "invoke request");
      const capability_id = request.capability_id || request.tool_name;
      const capability_version = request.capability_version || request.version || "1";
      const mode = assert_workspace_mode(request.workspace_mode || bound_workspace_mode || "light");
      if (bound_workspace_mode !== null && mode !== bound_workspace_mode) {
        throw new CapabilityToolError("workspace_mode_mismatch", "workspace mode does not match the gateway");
      }
      const registration = registrations.get(String(capability_id) + "@" + String(capability_version));
      if (!registration) throw new CapabilityToolError("capability_not_found", "capability is not registered");
      const item = registration.descriptor;
      if (!item.supported_workspace_modes.includes(mode)) {
        throw new CapabilityToolError("capability_mode_not_supported", "capability is not supported in this workspace mode");
      }
      const input = require_object(request.input || request.params || {}, "input");
      const provider_environment_broker = invocation_environment_broker(environment_broker, request);
      const raw_result = await registration.provider.invoke({
        descriptor: item,
        request: Object.freeze({ ...request }),
        input,
        workspace_mode: mode,
        tool_call_id: request.tool_call_id || "call_local",
        signal: request.signal,
        artifact_store: provider_artifact_store,
        environment_broker: provider_environment_broker,
      });
      const result = raw_result && typeof raw_result === "object" && !Array.isArray(raw_result)
        && Object.prototype.hasOwnProperty.call(raw_result, "output")
        ? raw_result
        : { output: raw_result, artifacts: [] };
      const artifacts = result.artifacts === undefined ? [] : result.artifacts;
      if (!Array.isArray(artifacts) || artifacts.some((value) => typeof value !== "string")) {
        throw new CapabilityToolError("invalid_provider_result", "provider result artifacts must be an array of strings");
      }
      return {
        protocol: "tool_result",
        version: 1,
        tool_name: item.capability_id,
        tool_call_id: request.tool_call_id || "call_local",
        status: "ok",
        output: result.output,
        artifacts,
      };
    },
  };
  const port = create_tool_gateway_port(gateway);
  // Keep the extra Host-only registry methods on the returned port while
  // preserving the language-neutral tool_gateway_1 protocol shape.
  return Object.freeze({
    ...port,
    // Host-only assembly metadata.  The generic ToolGateway contract does
    // not expose filesystem or artifact operations, but a composition root
    // may reuse this exact store when it records compute outputs in Kernel.
    artifact_store: provider_artifact_store,
    register_provider: gateway.register_provider,
    unregister_provider: gateway.unregister_provider,
    list_providers: gateway.list_providers,
  });
}
