import { createHash } from "node:crypto";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";

const SYS_PROMPT_PARAMETERS = Type.Object({}, { additionalProperties: false });
const ORIGINS = new Set(["native", "skill", "extension", "unknown"]);
const ATTRIBUTIONS = new Set(["exact", "structured", "observed", "unattributed"]);
const RUNTIMES = new Set(["native-app-server", "pi-extension"]);

export function createPromptContributor(origin, contributor) {
  if (!ORIGINS.has(origin)) throw new TypeError(`invalid system prompt origin: ${origin}`);
  if (!contributor || typeof contributor.source !== "string" || !contributor.source) {
    throw new TypeError(`invalid ${origin} system prompt contributor`);
  }
  const attribution = contributor.attribution || "exact";
  if (!ATTRIBUTIONS.has(attribution)) {
    throw new TypeError(`invalid ${origin} system prompt attribution: ${attribution}`);
  }
  if (attribution === "exact" && typeof contributor.text !== "string") {
    throw new TypeError(`exact ${origin} system prompt contributor requires text`);
  }
  if (contributor.text !== undefined && typeof contributor.text !== "string") {
    throw new TypeError(`invalid ${origin} system prompt contributor text`);
  }
  if (contributor.inputs !== undefined && !isStringArray(contributor.inputs)) {
    throw new TypeError(`invalid ${origin} system prompt contributor inputs`);
  }
  if (contributor.note !== undefined && typeof contributor.note !== "string") {
    throw new TypeError(`invalid ${origin} system prompt contributor note`);
  }
  if (contributor.metadata !== undefined && !isRecord(contributor.metadata)) {
    throw new TypeError(`invalid ${origin} system prompt contributor metadata`);
  }
  return deepFreeze({
    origin,
    source: contributor.source,
    attribution,
    ...(contributor.inputs ? { inputs: [...contributor.inputs] } : {}),
    ...(contributor.text !== undefined
      ? { text: contributor.text, sha256: sha256Text(contributor.text) }
      : {}),
    ...(contributor.metadata ? { metadata: structuredClone(contributor.metadata) } : {}),
    ...(contributor.note ? { note: contributor.note } : {}),
  });
}

export function createSystemPromptManifest({
  runtime,
  effective,
  contributors,
  provenanceComplete,
  limitations = [],
}) {
  if (!RUNTIMES.has(runtime)) throw new TypeError(`invalid system prompt runtime: ${runtime}`);
  if (typeof effective !== "string") throw new TypeError("effective system prompt must be text");
  if (!Array.isArray(contributors) || contributors.length === 0) {
    throw new TypeError("system prompt contributors are required");
  }
  if (typeof provenanceComplete !== "boolean") {
    throw new TypeError("system prompt provenance completeness is required");
  }
  if (!isStringArray(limitations)) throw new TypeError("invalid system prompt limitations");
  const normalizedContributors = contributors.map((contributor) => (
    createPromptContributor(contributor?.origin, contributor)
  ));
  for (const contributor of normalizedContributors) {
    if (contributor.attribution === "exact" && !effective.includes(contributor.text)) {
      throw new TypeError(`exact ${contributor.origin} contributor is absent from the effective prompt`);
    }
  }
  return deepFreeze({
    schema_version: "tspi-system-prompt/2",
    runtime,
    effective,
    sha256: sha256Text(effective),
    provenance_complete: provenanceComplete,
    contributors: normalizedContributors,
    ...(limitations.length > 0 ? { limitations: [...limitations] } : {}),
  });
}

export function createSystemPromptTool(manifestOrResolver, { name = "sys_prompt" } = {}) {
  const resolveManifest = typeof manifestOrResolver === "function"
    ? manifestOrResolver
    : () => manifestOrResolver;
  return {
    name,
    label: "System Prompt",
    description: "Read the exact effective system prompt, attributable contributors, and explicit provenance gaps.",
    promptSnippet: "Inspect the effective system prompt and its provenance",
    parameters: SYS_PROMPT_PARAMETERS,
    async execute(_toolCallId, _params, _signal, _onUpdate, ctx) {
      const manifest = await resolveManifest(ctx);
      assertManifest(manifest);
      return {
        content: [{ type: "text", text: JSON.stringify(manifest, null, 2) }],
        details: {
          sha256: manifest.sha256,
          contributorCount: manifest.contributors.length,
          provenanceComplete: manifest.provenance_complete,
        },
      };
    },
  };
}

export function sha256Text(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function assertManifest(manifest) {
  if (
    manifest?.schema_version !== "tspi-system-prompt/2"
    || typeof manifest.effective !== "string"
    || !Array.isArray(manifest.contributors)
  ) {
    throw new TypeError("sys_prompt requires a TSPi system prompt manifest");
  }
}

function isStringArray(value) {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}
