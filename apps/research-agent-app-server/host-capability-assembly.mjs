/**
 * Host-owned provider assembly.
 *
 * Extension discovery returns an inventory only.  This module is the explicit
 * trust boundary that maps an inventory provider to a Host-supplied adapter
 * factory.  It never imports an entry path from a manifest and it never lets a
 * request choose an adapter or executable.
 */

import {
  create_environment_broker_adapter,
  normalize_environment_binding,
} from "../../packages/research-agent-capabilities/environment_binding.mjs";

export const HOST_CAPABILITY_ASSEMBLY_VERSION = "host_capability_assembly_1";

export class HostCapabilityAssemblyError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "HostCapabilityAssemblyError";
    this.code = code;
    this.details = details;
  }
}

// Notification is a Host-owned side-effect capability. Its transport and
// credentials remain outside Agent requests, but it is still part of the
// declarative capability catalog.
const KINDS = new Set(["compute", "analysis", "harness", "artifact", "notification"]);
const DIGEST = /^sha256:[0-9a-f]{64}$/u;

function fail(code, message, details = {}) {
  throw new HostCapabilityAssemblyError(code, message, details);
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("invalid_assembly", `${field} must be an object`);
  return value;
}

function entries_from(inventory) {
  const values = Array.isArray(inventory) ? inventory : inventory?.providers;
  if (!Array.isArray(values)) fail("invalid_inventory", "provider inventory must be an array or discovery result");
  const ids = new Set();
  return values.map((entry) => {
    object(entry, "provider inventory entry");
    if (typeof entry.id !== "string" || entry.id.length === 0) fail("invalid_inventory", "provider inventory id is required");
    if (ids.has(entry.id)) fail("invalid_inventory", `duplicate provider inventory id: ${entry.id}`);
    ids.add(entry.id);
    if (typeof entry.version !== "string" || entry.version.length === 0) fail("invalid_inventory", `provider ${entry.id} version is invalid`);
    if (typeof entry.kind !== "string" || !KINDS.has(entry.kind)) fail("invalid_inventory", `provider ${entry.id} kind is invalid`);
    if (entry.descriptor_digest !== undefined && (typeof entry.descriptor_digest !== "string" || !DIGEST.test(entry.descriptor_digest))) {
      fail("invalid_inventory", `provider ${entry.id} descriptor digest is invalid`);
    }
    const descriptor_provider_digest = entry.descriptor_data?.provider?.descriptor_digest
      ?? entry.descriptor_data?.descriptor_digest;
    if (descriptor_provider_digest !== undefined && (typeof descriptor_provider_digest !== "string" || !DIGEST.test(descriptor_provider_digest))) {
      fail("invalid_inventory", `provider ${entry.id} descriptor_data digest is invalid`);
    }
    return entry;
  });
}

function allowlist_entries(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) fail("invalid_allowlist", "provider allowlist must be an array");
  const ids = new Set();
  return value.map((entry) => {
    object(entry, "provider allowlist entry");
    const manifest_provider_id = entry.manifest_provider_id ?? entry.provider_id;
    const adapter_id = entry.adapter_id;
    if (typeof manifest_provider_id !== "string" || manifest_provider_id.length === 0) fail("invalid_allowlist", "manifest_provider_id is required");
    if (typeof adapter_id !== "string" || adapter_id.length === 0) fail("invalid_allowlist", "adapter_id is required");
    if (ids.has(manifest_provider_id)) fail("invalid_allowlist", `duplicate allowlist provider: ${manifest_provider_id}`);
    ids.add(manifest_provider_id);
    const digest = entry.descriptor_digest;
    if (digest !== undefined && (typeof digest !== "string" || !DIGEST.test(digest))) fail("invalid_allowlist", `allowlist digest is invalid for ${manifest_provider_id}`);
    const capability_ids = entry.capability_ids === undefined ? undefined : entry.capability_ids;
    if (capability_ids !== undefined && (!Array.isArray(capability_ids) || capability_ids.length === 0 || capability_ids.some((id) => typeof id !== "string" || id.length === 0))) {
      fail("invalid_allowlist", `allowlist capability_ids is invalid for ${manifest_provider_id}`);
    }
    const required_tool_ids = entry.required_tool_ids === undefined ? [] : entry.required_tool_ids;
    if (!Array.isArray(required_tool_ids) || required_tool_ids.some((id) => typeof id !== "string" || id.length === 0)) fail("invalid_allowlist", `allowlist required_tool_ids is invalid for ${manifest_provider_id}`);
    return Object.freeze({
      ...entry,
      manifest_provider_id,
      adapter_id,
      ...(digest === undefined ? {} : { descriptor_digest: digest }),
      ...(capability_ids === undefined ? {} : { capability_ids: Object.freeze([...new Set(capability_ids)]) }),
      required_tool_ids: Object.freeze([...new Set(required_tool_ids)]),
    });
  });
}

function provider_descriptors(provider) {
  if (!provider || typeof provider !== "object" || typeof provider.descriptors !== "function" || typeof provider.invoke !== "function") {
    fail("invalid_adapter", "trusted adapter must expose descriptors() and invoke()");
  }
  let values;
  try {
    values = Array.from(provider.descriptors());
  } catch (error) {
    fail("invalid_adapter", "trusted adapter descriptors() failed", { cause: String(error?.message || error) });
  }
  if (values.length === 0) fail("invalid_adapter", "trusted adapter must advertise at least one descriptor");
  return values;
}

function verify_adapter(entry, allow, provider) {
  if (provider.provider_id !== allow.adapter_id) fail("adapter_identity_mismatch", `adapter ${allow.adapter_id} returned provider_id ${String(provider.provider_id)}`);
  if (allow.adapter_version !== undefined && provider.provider_version !== allow.adapter_version) fail("adapter_version_mismatch", `adapter ${allow.adapter_id} version does not match allowlist`);
  if (allow.kind !== undefined && entry.kind !== allow.kind) fail("provider_kind_mismatch", `provider ${entry.id} kind does not match allowlist`);
  if (allow.version !== undefined && entry.version !== allow.version) fail("provider_version_mismatch", `provider ${entry.id} version does not match allowlist`);
  const inventory_digest = entry.descriptor_digest ?? entry.descriptor_data?.descriptor_digest;
  if (allow.descriptor_digest !== undefined && inventory_digest !== allow.descriptor_digest) fail("descriptor_digest_mismatch", `provider ${entry.id} descriptor digest does not match allowlist`);
  if (inventory_digest !== undefined && allow.descriptor_digest === undefined) fail("descriptor_digest_required", `allowlist must pin descriptor digest for ${entry.id}`);
  const descriptors = provider_descriptors(provider);
  for (const descriptor of descriptors) {
    if (!descriptor || typeof descriptor !== "object" || descriptor.kind !== entry.kind) fail("provider_kind_mismatch", `adapter ${allow.adapter_id} descriptor kind does not match inventory`);
    if (descriptor.provider?.provider_id !== undefined && descriptor.provider.provider_id !== provider.provider_id) fail("adapter_identity_mismatch", "adapter descriptor provider_id does not match adapter");
  }
  if (allow.capability_ids !== undefined) {
    const actual = descriptors.map((descriptor) => descriptor.capability_id);
    if (actual.length !== allow.capability_ids.length || actual.some((id, index) => id !== allow.capability_ids[index])) fail("capability_inventory_mismatch", `adapter ${allow.adapter_id} capability inventory does not match allowlist`);
  }
  const trusted_digest = allow.trusted_descriptor_digest
    ?? entry.descriptor_data?.provider?.descriptor_digest;
  if (trusted_digest !== undefined) {
    if (typeof trusted_digest !== "string" || !DIGEST.test(trusted_digest)) fail("invalid_allowlist", "trusted_descriptor_digest is invalid");
    const actual = descriptors.map((descriptor) => descriptor.provider?.descriptor_digest).filter(Boolean);
    if (actual.length === 0 || !actual.includes(trusted_digest)) fail("trusted_descriptor_digest_mismatch", `adapter ${allow.adapter_id} descriptor digest is not trusted`);
  }
  return descriptors;
}

function catalog_entry(entry, allow, provider, descriptors) {
  return Object.freeze({
    manifest_provider_id: entry.id,
    manifest_version: entry.version,
    adapter_id: provider.provider_id,
    adapter_version: provider.provider_version ?? "1",
    kind: entry.kind,
    descriptor_digest: entry.descriptor_digest ?? entry.descriptor_data?.descriptor_digest ?? null,
    capabilities: Object.freeze(descriptors.map((descriptor) => Object.freeze({
      capability_id: descriptor.capability_id,
      capability_version: descriptor.capability_version,
      kind: descriptor.kind,
    }))),
  });
}

/**
 * Assemble only the explicitly allowlisted inventory providers.
 *
 * `adapters` is a Host-owned map of adapter IDs to factories.  An extension's
 * `entry` path is never imported here; callers must deliberately provide the
 * trusted factory in code/configuration.
 */
export function create_host_capability_assembly({
  inventory,
  allowlist,
  adapters = {},
  artifact_store,
  environment_broker,
} = {}) {
  const entries = entries_from(inventory);
  const selected = allowlist_entries(allowlist);
  if (!adapters || typeof adapters !== "object" || Array.isArray(adapters)) fail("invalid_adapters", "adapters must be an object map");
  if (artifact_store === undefined || artifact_store === null || typeof artifact_store !== "object") fail("artifact_store_required", "Host ArtifactStore is required for provider assembly");
  if (environment_broker === undefined || environment_broker === null || typeof environment_broker !== "object") fail("environment_broker_required", "Host EnvironmentBroker is required for provider assembly");
  const by_id = new Map(entries.map((entry) => [entry.id, entry]));
  const providers = [];
  const catalog = [];
  const records = [];
  const broker = create_environment_broker_adapter(environment_broker);
  for (const allow of selected) {
    const entry = by_id.get(allow.manifest_provider_id);
    if (!entry) fail("provider_not_in_inventory", `provider is not present in inventory: ${allow.manifest_provider_id}`);
    const factory = adapters[allow.adapter_id];
    if (typeof factory !== "function") fail("adapter_not_allowlisted", `trusted adapter factory is not registered: ${allow.adapter_id}`);
    let provider;
    try {
      provider = factory(Object.freeze({
        inventory: entry,
        allowlist: allow,
        artifact_store,
        environment_broker: broker,
      }));
    } catch (error) {
      fail("adapter_factory_failed", `trusted adapter factory failed: ${allow.adapter_id}`, { cause: String(error?.message || error) });
    }
    const descriptors = verify_adapter(entry, allow, provider);
    providers.push(provider);
    const item = catalog_entry(entry, allow, provider, descriptors);
    catalog.push(item);
    records.push(Object.freeze({ entry, allow, provider, descriptors: Object.freeze(descriptors) }));
  }
  const assembly = {
    protocol_version: HOST_CAPABILITY_ASSEMBLY_VERSION,
    providers: Object.freeze([...providers]),
    catalog() { return Object.freeze([...catalog]); },
    list_providers() { return Object.freeze([...catalog]); },
    async readiness({ manifest_provider_id, capability_id } = {}) {
      const matching = records.filter((record) => (manifest_provider_id === undefined || record.entry.id === manifest_provider_id)
        && (capability_id === undefined || record.descriptors.some((descriptor) => descriptor.capability_id === capability_id)));
      if (matching.length === 0) fail("provider_not_registered", "no assembled provider matches readiness request");
      const result = [];
      for (const record of matching) {
        const descriptors = capability_id === undefined
          ? record.descriptors
          : [record.descriptors.find((item) => item.capability_id === capability_id)];
        for (const descriptor of descriptors) {
          const requirement = {
            provider_id: record.provider.provider_id,
            capability_id: descriptor.capability_id,
            environment_kind: "compute",
            required_tool_ids: record.allow.required_tool_ids,
          };
          try {
            const binding = await broker.resolve(requirement);
            result.push(Object.freeze({
              manifest_provider_id: record.entry.id,
              adapter_id: record.provider.provider_id,
              capability_id: descriptor.capability_id,
              environment_id: binding.environment_id,
              environment_kind: binding.environment_kind,
              ...(binding.binding_digest === undefined ? {} : { binding_digest: binding.binding_digest }),
              readiness: binding.readiness ?? { state: "configured", checks: [] },
            }));
          } catch (error) {
            result.push(Object.freeze({
              manifest_provider_id: record.entry.id,
              adapter_id: record.provider.provider_id,
              capability_id: descriptor.capability_id,
              readiness: { state: "error", checks: [], reason: String(error?.message || error) },
            }));
          }
        }
      }
      return Object.freeze(result);
    },
  };
  return Object.freeze(assembly);
}

export { normalize_environment_binding };
