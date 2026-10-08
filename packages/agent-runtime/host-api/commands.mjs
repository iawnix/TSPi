import { readFileSync } from "node:fs";

const RESEARCH_KINDS = Object.freeze(["phase", "claim", "node", "finding", "gate", "attempt", "artifact", "lifecycle_action", "interpretation", "strategy"]);

const catalog = JSON.parse(readFileSync(
  new URL("../../tspi-runtime/tspi_runtime/command_catalog.json", import.meta.url),
  "utf8",
));
if (catalog.schema_version !== "tspi-command-catalog/1" || !Array.isArray(catalog.commands)) {
  throw new Error("invalid TSPi command catalog");
}

export const COMMAND_DEFINITIONS = Object.freeze(Object.fromEntries(catalog.commands.map(
  ({ id, domain, effect, required, allowed }) => [id, Object.freeze({
    id, domain, effect, required: Object.freeze([...required]), allowed: Object.freeze([...allowed]),
  })],
)));

export const COMMAND_IDS = Object.freeze(Object.keys(COMMAND_DEFINITIONS));

export const SLASH_COMMAND_DEFINITIONS = Object.freeze(Object.fromEntries(
  Object.entries(catalog.slash_commands).map(([key, definition]) => [key, Object.freeze({
    ...definition,
    completions: Object.freeze([...definition.completions]),
  })]),
));

export const SLASH_COMMAND_NAMES = Object.freeze(
  Object.values(SLASH_COMMAND_DEFINITIONS).map((definition) => `/${definition.name}`),
);

export function createCommandService(transport) {
  if (!transport || typeof transport.execute !== "function") {
    throw new TypeError("command service requires an execute transport");
  }
  return Object.freeze({
    execute(command, root, params = {}, signal) {
      const invocation = validateCommandInvocation(command, params);
      return transport.execute({ ...invocation, root, signal });
    },
  });
}

export function validateCommandInvocation(command, params = {}) {
  const definition = COMMAND_DEFINITIONS[command];
  if (!definition) throw new Error(`unsupported TSPi command: ${command}`);
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new Error(`${command} parameters must be an object`);
  }
  const normalized = { ...params };
  if (Object.keys(normalized).some((key) => /[A-Z]/.test(key))) {
    throw new Error("schema_field_invalid: command fields use snake_case");
  }
  const unsupported = Object.keys(normalized).filter((key) => !definition.allowed.includes(key));
  if (unsupported.length) throw new Error(`schema_field_invalid: ${command} unsupported fields: ${unsupported.sort().join(", ")}`);
  for (const key of definition.required) {
    if (normalized[key] === undefined || normalized[key] === null || normalized[key] === "") {
      throw new Error(`${command} requires ${key}`);
    }
  }
  if (command === "research.detail" && !RESEARCH_KINDS.includes(normalized.kind)) {
    throw new Error("research.detail kind must be phase, claim, node, finding, or gate");
  }
  return Object.freeze({ command, params: Object.freeze(normalized) });
}

export function commandArguments(command, params = {}) {
  const invocation = validateCommandInvocation(command, params);
  const args = [];
  const flags = {
    kind: "--kind",
    id: "--id",
    name: "--name",
    query: "--query",
    claim_id: "--claim-id",
    record_type: "--record-type",
    limit: "--limit",
    node_id: "--node-id", attempt_id: "--attempt-id", job_id: "--job-id",
    offset: "--offset", max_bytes: "--max-bytes",
    artifact_id: "--artifact-id",
    subject_id: "--subject-id",
    operation: "--operation",
  };
  const unsupported = Object.keys(invocation.params).filter((key) => !(key in flags) && key !== "event_ids");
  if (unsupported.length) {
    throw new Error(`unsupported_command_arguments: ${unsupported.sort().join(", ")}`);
  }
  for (const [key, flag] of Object.entries(flags)) {
    if (invocation.params[key] !== undefined) args.push(flag, String(invocation.params[key]));
  }
  for (const id of invocation.params.event_ids || []) args.push("--event-id", id);
  return args;
}

export function parseSlashCommand(name, input = "") {
  const definition = SLASH_COMMAND_DEFINITIONS[name];
  if (!definition) throw new Error(`unsupported slash command: /${name}`);
  const tokens = String(input).trim().split(/\s+/).filter(Boolean);
  if (name === "research") return parseResearchSlash(tokens, definition.usage);
  if (tokens.length > (name === "resume" ? 1 : 0)) throw usageError(definition.usage);
  return Object.freeze({ command: `client.${name}`, params: Object.freeze(tokens.length ? { sessionId: tokens[0] } : {}) });
}

export function slashCompletions(name, prefix = "") {
  const definition = SLASH_COMMAND_DEFINITIONS[name];
  if (!definition) return null;
  const candidate = String(prefix).trim().toLowerCase();
  const matches = definition.completions
    .filter((value) => value.startsWith(candidate))
    .map((value) => ({ value, label: value }));
  return matches.length ? matches : null;
}

function parseResearchSlash(tokens, usage) {
  const action = tokens[0] || "summary";
  if (["summary", "context", "liveness", "map", "decisions", "storage", "validate", "operations"].includes(action)
      && (tokens.length === 1 || (action === "summary" && tokens.length === 0))) {
    return Object.freeze({ command: `research.${action}`, params: Object.freeze({}) });
  }
  if (action === "detail" && tokens.length === 3) {
    return validateCommandInvocation("research.detail", { kind: tokens[1], id: tokens[2] });
  }
  if (action === "locate" && tokens.length > 1) {
    return validateCommandInvocation("research.locate", { query: tokens.slice(1).join(" ") });
  }
  throw usageError(usage);
}


function usageError(usage) {
  const error = new Error(`Usage: ${usage}`);
  error.name = "CommandUsageError";
  return error;
}
