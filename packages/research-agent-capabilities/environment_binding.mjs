/**
 * Normalize the Host-owned execution binding consumed by compute providers.
 *
 * Environment catalogs may expose a public binding (for example a Python
 * broker object with to_backend_binding()) or the JS shape directly.  The
 * provider boundary receives one canonical shape only.  The command and
 * environment are installation-owned values and must never be supplied by a
 * capability request.
 */

const SAFE_ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/u;
// Providers may receive an opaque installation digest.  The Host can enforce
// a full 64-hex digest when loading signed catalogs; the execution boundary
// only requires the stable sha256 namespace so test and remote brokers may use
// opaque labels without exposing installation details.
const DIGEST = /^sha256:[A-Za-z0-9._:-]{1,128}$/u;
const READINESS_STATES = new Set(["configured", "ready", "not_ready", "unknown", "error", "unavailable"]);

export class EnvironmentBindingError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "EnvironmentBindingError";
    this.code = code;
    this.details = details;
  }
}

function object(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new EnvironmentBindingError("invalid_environment_binding", `${field} must be an object`);
  }
  return value;
}

function command_from(value) {
  const command = value.command ?? (value.executable === undefined ? value.argv : [value.executable]);
  if (!Array.isArray(command) || command.length === 0
      || command.some((item) => typeof item !== "string" || item.length === 0 || item.includes("\0"))) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment binding must provide a non-empty command argv");
  }
  return Object.freeze([...command]);
}

function backend_binding(value) {
  if (typeof value.to_backend_binding !== "function") return value;
  let backend;
  try {
    backend = value.to_backend_binding();
  } catch (error) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment broker could not expose its backend binding", {
      cause: String(error?.message || error),
    });
  }
  object(backend, "backend binding");
  return {
    ...value,
    ...backend,
    // Public EnvironmentBinding fields must win over backend aliases below.
    environment_id: value.environment_id ?? value.environment ?? backend.environment_id ?? backend.environment,
    environment_kind: value.environment_kind ?? value.kind ?? backend.environment_kind ?? backend.kind,
    binding_digest: value.binding_digest ?? backend.binding_digest,
    readiness: value.readiness ?? backend.readiness,
  };
}

/**
 * Convert a broker result into the canonical JS provider binding.
 *
 * The returned object is intentionally immutable.  It contains an argv and
 * environment only because trusted Host code needs those values to spawn the
 * selected executable; callers cannot set either field through a capability
 * input.
 */
export function normalize_environment_binding(value, requirement = {}) {
  const raw = backend_binding(object(value, "environment binding"));
  const environment_id = raw.environment_id ?? raw.environment;
  if (typeof environment_id !== "string" || environment_id.length === 0 || environment_id.length > 128) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment binding has no environment_id");
  }
  const environment_kind = raw.environment_kind ?? raw.kind ?? requirement.environment_kind ?? "compute";
  if (typeof environment_kind !== "string" || environment_kind.length === 0 || environment_kind.length > 64) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment binding has no environment_kind");
  }
  const env = raw.env ?? raw.environment_variables ?? raw.environment_vars ?? raw.environment_map ?? raw.environment;
  // `environment` is the historical environment name in Python bindings, so
  // only treat it as an env map when it is actually an object.
  const env_map = env && typeof env === "object" && !Array.isArray(env) ? env : {};
  if (Object.keys(env_map).some((key) => !SAFE_ENV_KEY.test(key) || typeof env_map[key] !== "string" || env_map[key].includes("\0"))) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment binding env is invalid");
  }
  const binding_digest = raw.binding_digest;
  if (binding_digest !== undefined && (typeof binding_digest !== "string" || !DIGEST.test(binding_digest))) {
    throw new EnvironmentBindingError("invalid_environment_binding", "environment binding digest is invalid");
  }
  const readiness = raw.readiness;
  let normalized_readiness;
  if (readiness !== undefined) {
    const readiness_object = object(readiness, "readiness");
    if (typeof readiness_object.state !== "string" || !READINESS_STATES.has(readiness_object.state)) {
      throw new EnvironmentBindingError("invalid_environment_binding", "environment readiness state is invalid");
    }
    const checks = readiness_object.checks === undefined ? [] : readiness_object.checks;
    if (!Array.isArray(checks) || checks.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
      throw new EnvironmentBindingError("invalid_environment_binding", "environment readiness checks are invalid");
    }
    normalized_readiness = Object.freeze({
      state: readiness_object.state,
      checks: Object.freeze(checks.map((item) => Object.freeze({ ...item }))),
      ...(readiness_object.reason === undefined ? {} : { reason: String(readiness_object.reason) }),
    });
  }
  return Object.freeze({
    schema_version: "research-agent-environment-binding/1",
    capability_id: typeof raw.capability_id === "string" ? raw.capability_id : requirement.capability_id,
    provider_id: typeof raw.provider_id === "string" ? raw.provider_id : requirement.provider_id,
    environment_id,
    environment_kind,
    ...(typeof raw.execution_kind === "string" ? { execution_kind: raw.execution_kind } : {}),
    command: command_from(raw),
    env: Object.freeze({ ...env_map }),
    ...(binding_digest === undefined ? {} : { binding_digest }),
    ...(normalized_readiness === undefined ? {} : { readiness: normalized_readiness }),
  });
}

function resolver_for(broker) {
  object(broker, "EnvironmentBroker");
  const resolver = broker.resolve ?? broker.bind;
  if (typeof resolver !== "function") {
    throw new EnvironmentBindingError("environment_unavailable", "EnvironmentBroker must expose resolve() or bind()");
  }
  return resolver;
}

/**
 * Wrap a Host EnvironmentBroker so all providers consume the canonical shape.
 * The wrapper never discovers an executable and never falls back to PATH.
 */
export function create_environment_broker_adapter(broker) {
  const host = object(broker, "EnvironmentBroker");
  const resolve_binding = async (requirement = {}) => {
    const resolver = resolver_for(host);
    let raw;
    try {
      raw = await resolver.call(host, Object.freeze({ ...requirement }));
    } catch (error) {
      if (error instanceof EnvironmentBindingError) throw error;
      throw new EnvironmentBindingError("environment_unavailable", "EnvironmentBroker could not resolve a binding", {
        cause: String(error?.message || error),
      });
    }
    return normalize_environment_binding(raw, requirement);
  };
  return Object.freeze({
    protocol_version: "environment_broker_1",
    resolve: resolve_binding,
    bind: resolve_binding,
  });
}
