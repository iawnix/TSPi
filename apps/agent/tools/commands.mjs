import catalog from "./command-catalog.json" with { type: "json" };
import { Value } from "../pi/typebox.mjs";

if (catalog.schema_version !== "research-agent-command-catalog/1" || !Array.isArray(catalog.commands)) {
  throw new Error("invalid ResearchAgent command catalog");
}

export const COMMAND_DEFINITIONS = Object.freeze(Object.fromEntries(catalog.commands.map(
  ({ id, domain, effect, required, allowed, schema, result }) => [id, Object.freeze({
    id, domain, effect, schema, result, required: Object.freeze([...required]), allowed: Object.freeze([...allowed]),
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
  if (!definition) throw new Error(`unsupported ResearchAgent command: ${command}`);
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    throw new Error(`${command} parameters must be an object`);
  }
  const normalized = { ...params };
  if (!Value.Check(definition.schema, normalized)) {
    const errors = Value.Errors(definition.schema, normalized);
    const detail = errors.map(error => `${error.instancePath || "/"}: ${error.message}`).join("; ");
    throw new Error(`schema_field_invalid: ${command}: ${detail}`);
  }
  return Object.freeze({ command, params: Object.freeze(normalized) });
}

export function commandArguments(command, params = {}) {
  const invocation = validateCommandInvocation(command, params);
  const args = [];
  const fields = ["ref", "query", "origin", "limit", "offset", "after_sequence", "job_id", "artifact_id", "event_id"];
  for (const [key, value] of Object.entries(invocation.params)) {
    if (!fields.includes(key)) throw new Error(`unsupported_command_arguments: ${key}`);
    args.push("--" + key.replaceAll("_", "-"), String(value));
  }
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
  const action = tokens[0] || "read";
  if (action === "read" && tokens.length <= 2) return validateCommandInvocation("research.read", tokens[1] ? {ref: tokens[1]} : {});
  if (action === "search") return validateCommandInvocation("research.search", {query: tokens.slice(1).join(" ")});

  throw usageError(usage);
}


function usageError(usage) {
  const error = new Error(`Usage: ${usage}`);
  error.name = "CommandUsageError";
  return error;
}
