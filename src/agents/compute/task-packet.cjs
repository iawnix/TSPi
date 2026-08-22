"use strict";

const { realpathSync, statSync } = require("node:fs");
const { isAbsolute } = require("node:path");
const {
  serializeAgentDocument,
  validateAgentTask,
} = require("../../agent-core/agent-protocol.cjs");

const COMPUTE_RESULT_TOOL_NAME = "ts_compute_result";
const COMPUTE_ACTION_TOOL_NAMES = Object.freeze({
  prepare: "ts_workspace_compute_prepare",
  submit: "ts_workspace_compute_submit",
  status: "ts_workspace_compute_status",
  tail: "ts_workspace_compute_tail",
  collect: "ts_workspace_compute_collect",
  parse: "ts_workspace_compute_parse",
  cancel: "ts_workspace_compute_cancel",
});
const COMPUTE_PLANS = Object.freeze({
  launch: Object.freeze({ required: Object.freeze(["prepare", "submit"]), optional: Object.freeze([]) }),
  inspect: Object.freeze({ required: Object.freeze(["status"]), optional: Object.freeze(["tail"]) }),
  finalize: Object.freeze({ required: Object.freeze(["collect", "parse"]), optional: Object.freeze([]) }),
  cancel: Object.freeze({ required: Object.freeze(["cancel"]), optional: Object.freeze([]) }),
});
const OBJECTIVES = Object.freeze({
  launch: "Prepare the bound calculation intent and submit it exactly once.",
  inspect: "Inspect the bound remote calculation and optionally read one bounded diagnostic tail.",
  finalize: "Collect the bound remote artifacts and run the bound deterministic parser.",
  cancel: "Cancel the bound remote calculation exactly once.",
});
const MAX_COMPUTE_TASK_BYTES = 16 * 1024;

function buildComputeTask({
  runId,
  workspaceRoot,
  operation,
  backend,
  actId,
  binding,
  tailArtifact,
  tailLines,
  artifacts,
  artifactRef,
}) {
  const root = requireWorkspaceRoot(workspaceRoot);
  const plan = COMPUTE_PLANS[operation];
  if (!plan) throw new Error(`unsupported Compute operation: ${operation}`);
  if (!isPlainObject(binding)) throw new Error("Compute task requires a preflight binding");
  const taskId = requirePattern(runId, "runId", /^sub_[A-Za-z0-9-]+$/, 128);
  const normalizedActId = requirePattern(actId, "actId", /^act_[1-9][0-9]*$/, 128);
  const normalizedBackend = requireString(backend, "backend", 64);
  const intentId = requirePattern(binding.intentId, "binding.intentId", /^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$/, 128);
  const intentDigest = requirePattern(binding.intentDigest, "binding.intentDigest", /^sha256:[0-9a-f]{64}$/, 71);
  if (binding.executionKind !== "remote") {
    throw new Error(`Compute ${operation} requires a remote execution binding`);
  }
  const collectArtifacts = operation === "finalize"
    ? uniqueStrings(artifacts || [], "artifacts", 32, 255)
    : [];
  const parseArtifactRef = operation === "finalize"
    ? requireString(artifactRef, "artifactRef", 4096)
    : null;
  const inputs = {
    backend: normalizedBackend,
    act_id: normalizedActId,
    intent_id: intentId,
    intent_digest: intentDigest,
    execution_kind: "remote",
    required_actions: [...plan.required],
    optional_actions: [...plan.optional],
    tail: operation === "inspect"
      ? {
          artifact: tailArtifact === undefined ? null : requireString(tailArtifact, "tailArtifact", 255),
          lines: tailLines === undefined ? 80 : requireInteger(tailLines, "tailLines", 1, 500),
        }
      : null,
    collect_artifacts: collectArtifacts,
    parse_artifact_ref: parseArtifactRef,
  };
  const task = validateAgentTask({
    schema_version: "ts-agent-task/2",
    task_id: taskId,
    role: "compute",
    authority: "operational",
    operation,
    objective: OBJECTIVES[operation],
    workspace: { root, report_id: null, revision: null },
    scope: { report_id: null, act_refs: [normalizedActId], claim_refs: [] },
    inputs,
    capabilities: [
      ...plan.required.map((action) => COMPUTE_ACTION_TOOL_NAMES[action]),
      ...plan.optional.map((action) => COMPUTE_ACTION_TOOL_NAMES[action]),
      COMPUTE_RESULT_TOOL_NAME,
    ],
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: "execution_mirror",
      external_side_effects: ["launch", "cancel"].includes(operation),
    },
    output_contract: "ts-agent-result/1",
  });
  validateComputeTask(task);
  return task;
}

function validateComputeTask(value) {
  const task = validateAgentTask(value);
  if (task.role !== "compute" || task.authority !== "operational") {
    throw new Error("Compute task requires role=compute and authority=operational");
  }
  const plan = COMPUTE_PLANS[task.operation];
  if (!plan) throw new Error(`unsupported Compute operation: ${task.operation}`);
  const expectedCapabilities = [
    ...plan.required.map((action) => COMPUTE_ACTION_TOOL_NAMES[action]),
    ...plan.optional.map((action) => COMPUTE_ACTION_TOOL_NAMES[action]),
    COMPUTE_RESULT_TOOL_NAME,
  ];
  if (JSON.stringify(task.capabilities) !== JSON.stringify(expectedCapabilities)) {
    throw new Error("Compute task capabilities do not match its fixed action plan");
  }
  const bytes = Buffer.byteLength(serializeAgentDocument(task), "utf8");
  if (bytes > MAX_COMPUTE_TASK_BYTES) {
    throw new Error(`Compute task exceeds ${MAX_COMPUTE_TASK_BYTES} bytes`);
  }
  return task;
}

function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !isAbsolute(value)) throw new Error("workspace root must be absolute");
  const root = realpathSync(value);
  if (!statSync(root).isDirectory()) throw new Error("workspace root must be a directory");
  return root;
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function requirePattern(value, label, pattern, maxLength) {
  const text = requireString(value, label, maxLength);
  if (!pattern.test(text)) throw new Error(`${label} has an invalid format`);
  return text;
}

function requireInteger(value, label, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return value;
}

function uniqueStrings(value, label, maxItems, maxLength) {
  if (!Array.isArray(value) || value.length > maxItems) throw new Error(`${label} must contain at most ${maxItems} items`);
  const result = value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  COMPUTE_ACTION_TOOL_NAMES,
  COMPUTE_PLANS,
  COMPUTE_RESULT_TOOL_NAME,
  MAX_COMPUTE_TASK_BYTES,
  buildComputeTask,
  validateComputeTask,
};
