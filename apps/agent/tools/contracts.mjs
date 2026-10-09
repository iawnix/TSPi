import shared from "../../../contracts/commands/shared.json" with { type: "json" };

const TOOL_ROWS = [
  ["systemPrompt", "system_prompt", "deterministic_runtime"],
  ["state", "research_read", "deterministic_workspace"],
  ["search", "research_search", "deterministic_workspace"],
  ["create", "research_create", "deterministic_workspace"],
  ["update", "research_update", "deterministic_workspace"],
  ["result", "research_result", "deterministic_workspace"],
  ["jobStart", "job_start", "execution_runtime"],
  ["jobStatus", "job_status", "execution_runtime"],
  ["jobCollect", "job_collect", "execution_runtime"],
  ["jobCancel", "job_cancel", "execution_runtime"],
  ["jobProbe", "job_probe", "execution_runtime"],
  ["jobReconcile", "job_reconcile", "execution_runtime"],
  ["artifactRegister", "artifact_register", "deterministic_artifact"],
  ["artifactCreate", "artifact_create", "deterministic_artifact"],
  ["artifactRead", "artifact_read", "deterministic_artifact"],
];

// Semantic Harness names are the stable interface exposed to Agents. The
// Tool factories expose semantic names directly and are never duplicated in inventory.
export const PUBLIC_TOOL_NAMES = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([key, name]) => [key, name]),
));

export const PUBLIC_TOOL_EXECUTION = Object.freeze(Object.fromEntries(
  TOOL_ROWS.map(([, name, execution]) => [name, execution]),
));

// Canonical Harness metadata. Tool implementations remain transport adapters;
// this registry is the shared authority/effect/replay contract used by Hosts,
// audits, and future transports.
export const PUBLIC_TOOL_METADATA = Object.freeze({
  system_prompt: Object.freeze({ authority: "host_read", effect: "read", replay: "safe", phase: "orient" }),
  research_read: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  research_search: Object.freeze({ authority: "kernel_read", effect: "read", replay: "safe", phase: "orient" }),
  research_create: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  research_result: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "interpret" }),
  research_update: Object.freeze({ authority: "kernel_write", effect: "research_write", replay: "idempotent", phase: "advance" }),
  job_start: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "never", phase: "execute" }),
  job_status: Object.freeze({ authority: "execution_runtime", effect: "read", replay: "safe", phase: "execute" }),
  job_collect: Object.freeze({ authority: "execution_runtime", effect: "result_collection", replay: "idempotent", phase: "interpret" }),
  job_cancel: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "idempotent", phase: "execute" }),
  job_probe: Object.freeze({ authority: "execution_runtime", effect: "read", replay: "safe", phase: "prepare" }),
  job_reconcile: Object.freeze({ authority: "execution_runtime", effect: "execution_control", replay: "idempotent", phase: "execute" }),
  artifact_register: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  artifact_create: Object.freeze({ authority: "artifact_runtime", effect: "artifact_write", replay: "idempotent", phase: "prepare" }),
  artifact_read: Object.freeze({ authority: "artifact_runtime", effect: "read", replay: "safe", phase: "interpret" }),
});

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]*$/u;
const METADATA_FIELDS = Object.freeze(["authority", "effect", "replay", "phase"]);
const METADATA_VALUES = Object.freeze({
  authority: new Set([
    "host_read", "kernel_read", "kernel_write", "runtime_read", "advisory_runtime",
    "execution_runtime", "research_write", "artifact_runtime", "external_side_effect",
  ]),
  effect: new Set([
    "read", "research_write", "result_collection",
    "artifact_write", "execution_control", "external_write",
  ]),
  replay: new Set(["safe", "idempotent", "never"]),
  phase: new Set(["orient", "advance", "prepare", "execute", "interpret"]),
});

/** Validate one executable tool at the Harness admission boundary. */
export function validateHarnessToolDefinition(tool, { source = "tool", requireCanonical = true } = {}) {
  if (!tool || typeof tool !== "object" || Array.isArray(tool)) {
    throw new TypeError(`${source} must be an object`);
  }
  if (typeof tool.name !== "string" || !TOOL_NAME_PATTERN.test(tool.name)) {
    throw new TypeError(`${source} has an invalid tool name`);
  }
  if (typeof tool.label !== "string" || !tool.label.trim()) {
    throw new TypeError(`${source} ${tool.name} has no label`);
  }
  if (typeof tool.description !== "string" || !tool.description.trim()) {
    throw new TypeError(`${source} ${tool.name} has no description`);
  }
  if (!tool.parameters || typeof tool.parameters !== "object" || Array.isArray(tool.parameters)) {
    throw new TypeError(`${source} ${tool.name} has no parameter schema`);
  }
  if (typeof tool.execute !== "function") {
    throw new TypeError(`${source} ${tool.name} has no execute function`);
  }
  const metadata = tool.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    throw new TypeError(`${source} ${tool.name} has no Harness metadata`);
  }
  const keys = Object.keys(metadata).sort();
  const expectedKeys = [...METADATA_FIELDS].sort();
  if (keys.length !== expectedKeys.length || keys.some((key, index) => key !== expectedKeys[index])) {
    throw new TypeError(`${source} ${tool.name} has invalid Harness metadata fields`);
  }
  for (const field of METADATA_FIELDS) {
    if (typeof metadata[field] !== "string" || !METADATA_VALUES[field].has(metadata[field])) {
      throw new TypeError(`${source} ${tool.name} has invalid Harness metadata ${field}`);
    }
  }
  const canonical = PUBLIC_TOOL_METADATA[tool.name];
  if (requireCanonical && canonical && METADATA_FIELDS.some((field) => metadata[field] !== canonical[field])) {
    throw new TypeError(`${source} ${tool.name} metadata does not match the canonical Harness contract`);
  }
  return tool;
}

export function createPublicToolContracts(Type) {
  const contracts = {
    systemPrompt: contract("systemPrompt", "System Prompt", "Read the effective system prompt and its provenance.", Type.Unsafe(shared.tools.systemPrompt), {
      promptSnippet: "Inspect the effective system prompt and its provenance",
    }),
    state: contract("state", "Research memory", "Read a focused research snapshot: original tasks, important Nodes, their assessments and new execution facts. With ref, read a Node, immutable Result or record. For a large Node, specify field (goal/title/proposal/plan/progress/status/assessment_ref/subjects/relations) and page that field; only fully returned fields count as read for replacement. Follow returned pagination to inspect omitted details; reading never creates evidence dependencies. Read a Node before changing its proposal, plan, status, relations or assessment. The server tracks the revisions actually returned to this session.", Type.Unsafe(shared.tools.state)),
    search: contract("search", "Search research", "Find Nodes, Results and records by text. Empty query lists recent items. Filter by node_id, type, origin or after_sequence. Read a returned ref for its complete content; search does not establish an input or evidence relationship.", Type.Unsafe(shared.tools.search)),
    create: contract("create", "Create research Node", "Start an independently understandable research question or action. Only goal is required. Continue retries within the same Node; create another Node for an independent problem or branch. proposal describes a hypothesis or solution idea; plan describes how to investigate it. Optional relations express part_of, requires or alternative_to without maintaining reverse links. Example: {goal: 'Determine whether TS1 connects A and B', plan: 'Run forward and reverse IRC and inspect endpoints.'}.", Type.Unsafe(shared.tools.create), {executionMode: "sequential"}),
    update: contract("update", "Update research Node", "Append a note to an existing Node. Optionally revise proposal, plan, progress, status or explicit relations. A note alone never overwrites shared fields. Read the Node first when revising fields; a conflict leaves the whole update unapplied so you can read and reconsider. To retain a note independently, append it without field changes. open/paused/closed organize research; they neither determine scientific truth nor gate tools or cancel Jobs. assessment_ref explicitly selects an existing Result or note as the current synthesis. Example: {node_id: 'node_...', note: 'Optimization did not converge; this does not reject the pathway.', plan: 'Try another initial geometry.'}.", Type.Unsafe(shared.tools.update), {executionMode: "sequential"}),
    result: contract("result", "Publish research Result", "Save an immutable, citable outcome of a Node. conclusion is required and may report uncertainty or a negative result; observation distinguishes measured facts from interpretation. Cite exact inputs, evidence and existing artifact files. Use subjects for target/calculated fixed references and check_refs for scoped check evidence, including inconclusive checks. A new Result does not automatically replace older results or the current assessment. Use supersedes only for an explicit correction; as_assessment selects this Result as the Node synthesis, subject to the revision last read. With progress and as_assessment=true, publication and progress revision are atomic; a conflict saves neither. Without progress, a selection conflict leaves the Result saved. Review notices identify changed context or superseded inputs, not scientific invalidity. Example: {node_id: 'node_...', conclusion: 'This candidate connects A to C, not the requested B.', limitations: 'Only one conformer examined.'}.", Type.Unsafe(shared.tools.result), {executionMode: "sequential"}),
    jobStart: contract("jobStart", "Start Job", "Start a durable scientific computation Job. Pass a reviewed request_file with its request_sha256; Job Runtime resolves it and registers its immutable prepared_ref at submission. Existing prepared_ref values can be reused. Bind every research Job to an explicit node_id. For prepared submissions, node_id remains an outer binding; pass the reference/digest and optional timeout_seconds/repeat/root; request_id, work_id, command and execution fields are already fixed inside the request. Use native bash for report formatting and request preparation; these do not create calculation Jobs.", Type.Unsafe(shared.tools.jobStart), { executionMode: "sequential", replay: "never" }),
    jobStatus: contract("jobStatus", "Job Status", "Read the status of a durable job.", Type.Unsafe(shared.tools.jobStatus), { executionMode: "sequential" }),
    jobCollect: contract("jobCollect", "Collect Job", "Collect declared job outputs without requiring a domain parser.", Type.Unsafe(shared.tools.jobCollect), { executionMode: "sequential" }),
    jobCancel: contract("jobCancel", "Cancel Job", "Cancel a durable job.", Type.Unsafe(shared.tools.jobCancel), { executionMode: "sequential" }),
    jobProbe: contract("jobProbe", "Probe Job", "Probe execution platform availability.", Type.Unsafe(shared.tools.jobProbe), { executionMode: "sequential" }),
    jobReconcile: contract("jobReconcile", "Reconcile Job", "Reconcile an uncertain job receipt.", Type.Unsafe(shared.tools.jobReconcile), { executionMode: "sequential" }),
    artifactRegister: contract("artifactRegister", "Register Artifact", "Register an existing raw file as an evidence artifact.", Type.Unsafe(shared.tools.artifactRegister), { executionMode: "sequential" }),
    artifactCreate: contract("artifactCreate", "Create Artifact", "Create a raw or derived artifact from supplied content.", Type.Unsafe(shared.tools.artifactCreate), { executionMode: "sequential" }),
    artifactRead: contract("artifactRead", "Read Artifact", "Read bounded content or metadata from an artifact.", Type.Unsafe(shared.tools.artifactRead), { executionMode: "sequential" }),

  };
  return Object.freeze(Object.fromEntries(Object.entries(contracts).map(
    ([key, value]) => [key, Object.freeze(value)],
  )));
}

function contract(key, label, description, parameters, extra = {}) {
  const metadata = PUBLIC_TOOL_METADATA[PUBLIC_TOOL_NAMES[key]];
  if (!metadata) throw new Error(`missing Harness metadata for ${PUBLIC_TOOL_NAMES[key]}`);
  return {
    name: PUBLIC_TOOL_NAMES[key],
    label,
    description,
    parameters,
    metadata,
    ...extra,
  };
}
