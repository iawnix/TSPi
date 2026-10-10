import catalog from "./command-catalog.json" with { type: "json" };
import { Value } from "../pi/typebox.mjs";

if (catalog.schema_version !== "coragent-command-catalog/1" || !Array.isArray(catalog.commands)) {
  throw new Error("invalid CoRAgent command catalog");
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
  if (!definition) throw new Error(`unsupported CoRAgent command: ${command}`);
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
  if (name === "monitor") return parseMonitorSlash(tokens, definition.usage);
  if (tokens.length > (name === "resume" ? 1 : 0)) throw usageError(definition.usage);
  return Object.freeze({ command: `client.${name}`, params: Object.freeze(tokens.length ? { sessionId: tokens[0] } : {}) });
}

export function slashCompletions(name, prefix = "") {
  const definition = SLASH_COMMAND_DEFINITIONS[name];
  if (!definition) return null;
  const text = String(prefix);
  if (/[\r\n]/.test(text)) return null;
  const parts = text.trimStart().split(/\s+/);
  const fragment = parts.pop() || '';
  const base = parts.join(' ');
  const parent = base ? `${base} ` : '';
  let values = [...new Set(definition.completions.filter(value => value.startsWith(parent))
    .map(value => value.slice(parent.length).split(' ')[0]))];
  if (name === 'monitor') {
    const [action, operation, id] = parts;
    if (action === 'task' && operation === 'cancel' && id && parts.length === 3) {
      values = ['--keep-jobs', '--cancel-jobs'];
    } else if (['tasks', 'jobs', 'runs'].includes(action) || (action === 'run' && operation)) {
      const flags = parts.slice(action === 'run' ? 2 : 1);
      // A flag's value is user input, not another flag or a placeholder candidate.
      if (flags.length % 2 === 0) values = ['--limit', '--cursor', ...(['jobs', 'runs'].includes(action) ? ['--task'] : [])]
        .filter(flag => !flags.includes(flag));
      else values = [];
    }
  }
  const descriptions = {
    tasks: 'List research tasks', task: 'Inspect or control a task', jobs: 'List compute jobs',
    job: 'Inspect or cancel a job', runs: 'List execution records', run: 'Read execution details',
    health: 'Inspect service health', pause: 'Pause automatic continuation', resume: 'Resume automatic continuation',
    cancel: 'Cancel the selected task or job', read: 'Read research records', search: 'Search research records',
    '--keep-jobs': 'Keep compute jobs running', '--cancel-jobs': 'Request cancellation of compute jobs',
    '--limit': 'Page size: 1–100', '--cursor': 'Next-page cursor', '--task': 'Filter by task ID',
  };
  const matches = values.filter(value => value.toLowerCase().startsWith(fragment.toLowerCase()))
    .map(value => ({ value: parent + value + ' ', label: value, description: descriptions[value] }));
  return matches.length ? matches : null;
}

function parseResearchSlash(tokens, usage) {
  const action = tokens[0] || "read";
  if (action === "read" && tokens.length <= 2) return validateCommandInvocation("research.read", tokens[1] ? {ref: tokens[1]} : {});
  if (action === "search") return validateCommandInvocation("research.search", {query: tokens.slice(1).join(" ")});

  throw usageError(usage);
}

function parseMonitorSlash(tokens, usage) {
  const parts = [...tokens];
  const action = parts.shift() || "overview";
  const params = {};
  let method;
  if (!tokens.length || ["tasks", "jobs", "runs", "health"].includes(action)) {
    method = `monitor/${action}`;
    const allowed = ["tasks", "jobs", "runs"].includes(action)
      ? new Set(["--limit", "--cursor", ...(["jobs", "runs"].includes(action) ? ["--task"] : [])]) : new Set();
    const seen = new Set();
    while (parts.length) {
      const flag = parts.shift(), value = parts.shift();
      if (!allowed.has(flag)) throw usageError(usage, `Unknown option: ${flag}`);
      if (seen.has(flag)) throw usageError(usage, `Duplicate option: ${flag}`);
      if (!value || value.startsWith("--")) throw usageError(usage, `Missing value for ${flag}`);
      seen.add(flag);
      if (flag === "--limit") {
        if (!/^[1-9]\d*$/.test(value) || Number(value) > 100) throw usageError(usage, '--limit must be an integer from 1 to 100');
        params.limit = Number(value);
      } else params[flag === "--task" ? "user_task_id" : "cursor"] = value;
    }
  } else if (["task", "job", "run"].includes(action)) {
    const operation = parts.shift();
    const controls = action === "task" ? ["pause", "resume", "cancel"] : action === "job" ? ["cancel"] : [];
    const control = controls.includes(operation);
    const id = control ? parts.shift() : operation;
    if (!id || id.startsWith("--")) throw usageError(usage, `Missing ${action} ID`);
    params[{task:"user_task_id",job:"job_id",run:"run_id"}[action]] = id;
    method = `monitor/${action}/${control ? operation : "read"}`;
    if (action === "task" && operation === "cancel") {
      const jobs = parts.shift();
      if (!["--keep-jobs", "--cancel-jobs"].includes(jobs)) throw usageError(usage, 'Choose --keep-jobs or --cancel-jobs');
      params.jobs = jobs === "--keep-jobs" ? "keep" : "cancel";
    }
    if (action === "run") {
      const seen = new Set();
      while (parts.length) {
        const flag = parts.shift(), value = parts.shift();
        if (!["--limit", "--cursor"].includes(flag)) throw usageError(usage, `Unknown option: ${flag}`);
        if (seen.has(flag)) throw usageError(usage, `Duplicate option: ${flag}`);
        if (!value || value.startsWith("--")) throw usageError(usage, `Missing value for ${flag}`);
        seen.add(flag);
        if (flag === "--limit") {
          if (!/^[1-9]\d*$/.test(value) || Number(value) > 100) throw usageError(usage, '--limit must be an integer from 1 to 100');
          params.limit = Number(value);
        } else params.cursor = value;
      }
    }
    if (parts.length) throw usageError(usage);
  } else throw usageError(usage);
  return Object.freeze({command:"client.monitor", params:Object.freeze({method, ...params})});
}


function usageError(usage, reason) {
  const error = new Error(`${reason ? `${reason}\n` : ''}Usage: ${usage}`);
  error.name = "CommandUsageError";
  return error;
}
