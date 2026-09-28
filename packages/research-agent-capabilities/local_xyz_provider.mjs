/**
 * Deterministic, local geometry capability.
 *
 * This provider intentionally does not invoke a program or touch the
 * filesystem.  It demonstrates the provider lifecycle for simple inputs:
 * prepare -> execute -> parse -> finalize.  Artifact persistence and
 * environment selection remain Host-owned ports supplied by the gateway.
 */

const PROVIDER_ID = "local_geometry";
const PROVIDER_VERSION = "1";
const CAPABILITY_ID = "local_xyz_generate";
const MAX_XYZ_BYTES = 128 * 1024;

const GEOMETRIES = Object.freeze({
  water: Object.freeze({
    charge: 0,
    multiplicity: 1,
    xyz: "3\nwater (deterministic local geometry)\nO 0.000000 0.000000 0.000000\nH 0.758602 0.000000 0.504284\nH -0.758602 0.000000 0.504284\n",
  }),
  methane: Object.freeze({
    charge: 0,
    multiplicity: 1,
    xyz: "5\nmethane (deterministic local geometry)\nC 0.000000 0.000000 0.000000\nH 0.629118 0.629118 0.629118\nH -0.629118 -0.629118 0.629118\nH -0.629118 0.629118 -0.629118\nH 0.629118 -0.629118 -0.629118\n",
  }),
  methanol: Object.freeze({
    charge: 0,
    multiplicity: 1,
    xyz: "6\nmethanol (deterministic local geometry)\nC 0.000000 0.000000 0.000000\nO 1.430000 0.000000 0.000000\nH -0.363000 0.944000 0.000000\nH -0.363000 -0.944000 0.000000\nH -0.363000 0.000000 1.019000\nH 1.811000 0.763000 0.000000\n",
  }),
});

const DESCRIPTOR = Object.freeze({
  protocol: "capability_descriptor",
  version: 1,
  capability_id: CAPABILITY_ID,
  capability_version: "1",
  kind: "artifact",
  summary: "Generate a bounded deterministic XYZ geometry for a small named molecule.",
  input_schema: Object.freeze({
    type: "object",
    required: ["molecule"],
    properties: {
      molecule: { enum: ["water", "methane", "methanol"] },
      logical_ref: { type: "string", pattern: "^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$", maxLength: 256 },
    },
    additionalProperties: false,
  }),
  output_schema: Object.freeze({
    type: "object",
    required: ["artifact", "geometry"],
    properties: {
      artifact: { type: "object" },
      geometry: { type: "object" },
    },
    additionalProperties: false,
  }),
  supported_workspace_modes: Object.freeze(["light", "research"]),
  limits: Object.freeze({ max_xyz_bytes: MAX_XYZ_BYTES, molecule_count: 3 }),
  effects: Object.freeze(["artifact_create", "local_prepare", "local_execute", "local_parse", "local_finalize"]),
});

class LocalGeometryError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "LocalGeometryError";
    this.code = code;
    this.details = details;
  }
}

function assert_input(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new LocalGeometryError("invalid_input", "input must be an object");
  }
  if (typeof input.molecule !== "string" || !Object.hasOwn(GEOMETRIES, input.molecule)) {
    throw new LocalGeometryError("invalid_input", "molecule must be one of water, methane, or methanol");
  }
  const unknown = Object.keys(input).filter((key) => !["molecule", "logical_ref"].includes(key));
  if (unknown.length > 0) throw new LocalGeometryError("invalid_input", `unknown input field: ${unknown[0]}`);
  if (input.logical_ref !== undefined
    && (typeof input.logical_ref !== "string"
      || input.logical_ref.length === 0
      || input.logical_ref.length > 256
      || !/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/u.test(input.logical_ref)
      || input.logical_ref.split("/").some((segment) => segment === "." || segment === ".."))) {
    throw new LocalGeometryError("invalid_input", "logical_ref must be a relative path without traversal");
  }
  return Object.freeze({ molecule: input.molecule, ...(input.logical_ref ? { logical_ref: input.logical_ref } : {}) });
}

function parse_xyz(xyz) {
  const lines = xyz.trimEnd().split("\n");
  if (lines.length < 2) throw new LocalGeometryError("invalid_geometry", "generated XYZ is incomplete");
  const atom_count = Number.parseInt(lines[0], 10);
  if (!Number.isSafeInteger(atom_count) || atom_count < 1 || lines.length !== atom_count + 2) {
    throw new LocalGeometryError("invalid_geometry", "generated XYZ atom count is invalid");
  }
  const elements = {};
  for (const line of lines.slice(2)) {
    const fields = line.trim().split(/\s+/u);
    if (fields.length !== 4 || !/^[A-Z][a-z]?$/u.test(fields[0])) {
      throw new LocalGeometryError("invalid_geometry", "generated XYZ atom row is invalid");
    }
    const coordinates = fields.slice(1).map(Number);
    if (coordinates.some((coordinate) => !Number.isFinite(coordinate))) {
      throw new LocalGeometryError("invalid_geometry", "generated XYZ coordinates are not finite");
    }
    elements[fields[0]] = (elements[fields[0]] || 0) + 1;
  }
  return Object.freeze({ atom_count, elements: Object.freeze(elements) });
}

async function resolve_environment(environment_broker, input) {
  if (environment_broker === undefined || environment_broker === null) {
    return Object.freeze({ environment_id: "local_builtin", state: "not_required" });
  }
  if (typeof environment_broker !== "object" || Array.isArray(environment_broker)) {
    throw new LocalGeometryError("invalid_environment_broker", "environment_broker must be an object");
  }
  const resolver = environment_broker.resolve ?? environment_broker.bind;
  if (typeof resolver !== "function") {
    throw new LocalGeometryError("invalid_environment_broker", "environment_broker must expose resolve() or bind()");
  }
  const binding = await resolver.call(environment_broker, {
    provider_id: PROVIDER_ID,
    capability_id: CAPABILITY_ID,
    environment_kind: "local",
    input,
  });
  if (!binding || typeof binding !== "object" || Array.isArray(binding)) {
    throw new LocalGeometryError("invalid_environment_binding", "environment broker returned an invalid binding");
  }
  // Keep implementation details (commands, paths, credentials) outside the
  // provider plan and its output. Only stable public identity is retained.
  const environment_id = binding.environment_id ?? binding.environment ?? "local";
  if (typeof environment_id !== "string" || environment_id.length === 0 || environment_id.length > 128) {
    throw new LocalGeometryError("invalid_environment_binding", "environment binding has no valid environment id");
  }
  return Object.freeze({
    environment_id,
    ...(typeof binding.binding_digest === "string" ? { binding_digest: binding.binding_digest } : {}),
    ...(typeof binding.state === "string" ? { state: binding.state } : {}),
  });
}

function artifact_port(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || typeof value.create !== "function") {
    throw new LocalGeometryError("artifact_store_unavailable", "an ArtifactStore create() port is required");
  }
  return value;
}

function create_local_xyz_provider({ artifact_store, environment_broker } = {}) {
  const provider = {
    provider_id: PROVIDER_ID,
    provider_version: PROVIDER_VERSION,
    descriptors: () => [DESCRIPTOR],
    async prepare({ input, environment_broker: request_broker } = {}) {
      const normalized = assert_input(input);
      const geometry = GEOMETRIES[normalized.molecule];
      const xyz_bytes = Buffer.byteLength(geometry.xyz, "utf8");
      if (xyz_bytes > MAX_XYZ_BYTES) throw new LocalGeometryError("geometry_too_large", "generated geometry exceeds the size limit");
      const environment = await resolve_environment(request_broker ?? environment_broker, normalized);
      return Object.freeze({
        operation: CAPABILITY_ID,
        operation_version: "1",
        molecule: normalized.molecule,
        logical_ref: normalized.logical_ref ?? `inputs/${normalized.molecule}.xyz`,
        xyz: geometry.xyz,
        charge: geometry.charge,
        multiplicity: geometry.multiplicity,
        environment,
      });
    },
    async execute(prepared, context = {}) {
      if (!prepared || typeof prepared !== "object" || typeof prepared.xyz !== "string") {
        throw new LocalGeometryError("invalid_plan", "geometry execution plan is invalid");
      }
      const store = context.artifact_store ?? artifact_store;
      const port = artifact_port(store);
      const artifact = await port.create({
        content: prepared.xyz,
        artifact_type: "chemical/xyz",
        logical_ref: prepared.logical_ref,
        metadata: {
          molecule: prepared.molecule,
          charge: prepared.charge,
          multiplicity: prepared.multiplicity,
          provider_id: PROVIDER_ID,
          capability_id: CAPABILITY_ID,
          environment_id: prepared.environment.environment_id,
        },
      });
      if (!artifact || typeof artifact !== "object" || typeof artifact.artifact_id !== "string") {
        throw new LocalGeometryError("invalid_artifact", "ArtifactStore returned an invalid artifact manifest");
      }
      return Object.freeze({ artifact, xyz: prepared.xyz });
    },
    async parse(executed) {
      if (!executed || typeof executed !== "object" || typeof executed.xyz !== "string") {
        throw new LocalGeometryError("invalid_execution", "geometry execution result is invalid");
      }
      return Object.freeze({ geometry: parse_xyz(executed.xyz), xyz: executed.xyz });
    },
    async finalize({ prepared, executed, parsed } = {}) {
      if (!prepared || !executed?.artifact || !parsed?.geometry) {
        throw new LocalGeometryError("invalid_result", "geometry lifecycle result is incomplete");
      }
      return {
        output: {
          artifact: executed.artifact,
          geometry: parsed.geometry,
          molecule: prepared.molecule,
          charge: prepared.charge,
          multiplicity: prepared.multiplicity,
          environment: prepared.environment,
        },
        artifacts: [executed.artifact.artifact_id],
      };
    },
    async invoke({ input, artifact_store: request_store, environment_broker: request_broker } = {}) {
      const prepared = await provider.prepare({ input, environment_broker: request_broker });
      const executed = await provider.execute(prepared, { artifact_store: request_store });
      const parsed = await provider.parse(executed);
      return provider.finalize({ prepared, executed, parsed });
    },
  };
  return Object.freeze(provider);
}

export {
  CAPABILITY_ID as LOCAL_XYZ_CAPABILITY_ID,
  DESCRIPTOR as LOCAL_XYZ_DESCRIPTOR,
  LocalGeometryError,
  PROVIDER_ID as LOCAL_XYZ_PROVIDER_ID,
  create_local_xyz_provider,
};
