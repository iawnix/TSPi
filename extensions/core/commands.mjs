const RESEARCH_KINDS = Object.freeze(["phase", "claim", "node", "finding", "gate"]);

const definitions = [
  ["research.map", "research", "read", []],
  ["research.summary", "research", "read", []],
  ["research.detail", "research", "read", ["kind", "id"]],
  ["research.locate", "research", "read", ["query"]],
  ["research.validate", "research", "read", []],
  ["research.operations", "research", "read", []],
  ["research.change", "research", "write", ["request"]],
  ["compute.environments", "compute", "read", []],
  ["compute.environment", "compute", "read", ["name"]],
  ["compute.capabilities", "compute", "read", []],
  ["compute.artifacts", "compute", "read", []],
  ["compute.runs", "compute", "read", []],
];

export const COMMAND_DEFINITIONS = Object.freeze(Object.fromEntries(definitions.map(
  ([id, domain, effect, required]) => [id, Object.freeze({
    id,
    domain,
    effect,
    required: Object.freeze(required),
  })],
)));

export const COMMAND_IDS = Object.freeze(Object.keys(COMMAND_DEFINITIONS));

export const SLASH_COMMAND_DEFINITIONS = Object.freeze({
  research: Object.freeze({
    name: "research",
    description: "Read or validate the current ResearchMap.",
    usage: "/research [summary|map|detail <kind> <id>|locate <query>|validate|operations]",
    completions: Object.freeze(["summary", "map", "detail", "locate", "validate", "operations"]),
  }),
  compute: Object.freeze({
    name: "compute",
    description: "Inspect configured local and remote compute environments.",
    usage: "/compute [list|show <environment>]",
    completions: Object.freeze(["list", "show"]),
  }),
  runs: Object.freeze({
    name: "runs",
    description: "Browse active and recorded Compute and Review runs.",
    usage: "/runs",
    completions: Object.freeze([]),
  }),
  debug: Object.freeze({
    name: "debug",
    description: "Inspect TSPi runtime diagnostics.",
    usage: "/debug prompt",
    completions: Object.freeze(["prompt"]),
  }),
});

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
    nodeId: "--node-id",
  };
  for (const [key, flag] of Object.entries(flags)) {
    if (invocation.params[key] !== undefined) args.push(flag, String(invocation.params[key]));
  }
  return args;
}

export function parseSlashCommand(name, input = "") {
  const definition = SLASH_COMMAND_DEFINITIONS[name];
  if (!definition) throw new Error(`unsupported slash command: /${name}`);
  const tokens = String(input).trim().split(/\s+/).filter(Boolean);
  if (name === "research") return parseResearchSlash(tokens, definition.usage);
  if (name === "compute") return parseComputeSlash(tokens, definition.usage);
  if (name === "runs") {
    if (tokens.length) throw usageError(definition.usage);
    return Object.freeze({ command: "compute.runs", params: Object.freeze({}) });
  }
  if (tokens.length !== 1 || tokens[0] !== "prompt") throw usageError(definition.usage);
  return Object.freeze({ command: "client.debug.prompt", params: Object.freeze({}) });
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
  if (["summary", "map", "validate", "operations"].includes(action)
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

function parseComputeSlash(tokens, usage) {
  const action = tokens[0] || "list";
  if (action === "list" && tokens.length <= 1) {
    return Object.freeze({ command: "compute.environments", params: Object.freeze({}) });
  }
  if (action === "show" && tokens.length === 2) {
    return validateCommandInvocation("compute.environment", { name: tokens[1] });
  }
  throw usageError(usage);
}

function usageError(usage) {
  const error = new Error(`Usage: ${usage}`);
  error.name = "CommandUsageError";
  return error;
}
