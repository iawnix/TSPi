"use strict";

const { realpathSync, statSync } = require("node:fs");
const { isAbsolute } = require("node:path");
const {
  serializeAgentDocument,
  validateAgentTask,
} = require("../../agent-core/agent-protocol.cjs");
const {
  COMPUTE_RESULT_TOOL_NAME,
  schedulerPlanFor,
} = require("./scheduler-plan.cjs");
const MAX_COMPUTE_TASK_BYTES = 16 * 1024;

function buildComputeTask({
  runId,
  workspaceRoot,
  operation,
  capability,
  capabilityVersion,
  capabilityDescriptor,
  actionPlan,
  nodeId,
  binding,
  tailArtifact,
  tailLines,
  artifacts,
  artifactRef,
}) {
  const root = requireWorkspaceRoot(workspaceRoot);
  if (!isPlainObject(binding)) throw new Error("Compute task requires a preflight binding");
  const taskId = requirePattern(runId, "runId", /^sub_[1-9][0-9]*$/, 128);
  const normalizedNodeId = requirePattern(nodeId, "nodeId", /^node_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/, 128);
  const normalizedCapability = requirePattern(
    capability,
    "capability",
    /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/,
    128,
  );
  const normalizedCapabilityVersion = requirePattern(
    capabilityVersion,
    "capabilityVersion",
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/,
    32,
  );
  const descriptor = normalizeCapabilityDescriptor(
    capabilityDescriptor,
    normalizedCapability,
    normalizedCapabilityVersion,
  );
  const plan = schedulerPlanFor(
    operation,
    actionPlan || (descriptor.action_plan && descriptor.action_plan[operation]),
  );
  const descriptorDigest = requirePattern(
    binding.capabilityDescriptorDigest || binding.capability_descriptor_digest,
    "binding.capabilityDescriptorDigest",
    /^sha256:[0-9a-f]{64}$/,
    71,
  );
  const intentId = requirePattern(binding.intentId, "binding.intentId", /^calc_[1-9][0-9]*$/, 128);
  const intentDigest = requirePattern(binding.intentDigest, "binding.intentDigest", /^sha256:[0-9a-f]{64}$/, 71);
  if (!["local", "remote"].includes(binding.executionKind)) {
    throw new Error(`Compute ${operation} requires a local or remote execution binding`);
  }
  const collectArtifacts = operation === "finalize"
    ? uniqueStrings(artifacts || [], "artifacts", 32, 255)
    : [];
  const parseArtifactRef = operation === "finalize"
    ? requireString(artifactRef, "artifactRef", 4096)
    : null;
  const inputs = {
    capability: normalizedCapability,
    capability_version: normalizedCapabilityVersion,
    capability_descriptor_digest: descriptorDigest,
    capability_descriptor: descriptor,
    expected_output_roles: [...descriptor.output_roles],
    node_id: normalizedNodeId,
    intent_id: intentId,
    intent_digest: intentDigest,
    execution_kind: binding.executionKind,
    required_actions: [...plan.required],
    optional_actions: [...plan.optional],
    action_bindings: plan.bindings.map((item) => ({ ...item })),
    primary_action: plan.primary,
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
    schema_version: "tspi-task/2",
    task_id: taskId,
    role: "compute",
    authority: "operational",
    operation,
    objective: `Execute the declared ${operation} scheduler operation for the bound calculation.`,
    workspace: { root, report_id: null, revision: null },
    scope: { report_id: null, node_refs: [normalizedNodeId], claim_refs: [] },
    inputs,
    capabilities: [
      ...plan.bindings.map((action) => action.tool),
      COMPUTE_RESULT_TOOL_NAME,
    ],
    constraints: {
      canonical_workspace_mutation: false,
      scientific_decision: false,
      recursive_delegation: false,
      remote_authority: binding.executionKind === "remote" ? "execution_mirror" : "local_process",
      external_side_effects: ["launch", "cancel"].includes(operation),
    },
    output_contract: "tspi-result/1",
  });
  validateComputeTask(task);
  return task;
}

function validateComputeTask(value) {
  const task = validateAgentTask(value);
  if (task.role !== "compute" || task.authority !== "operational") {
    throw new Error("Compute task requires role=compute and authority=operational");
  }
  const inputs = task.inputs;
  const bindings = Array.isArray(inputs.action_bindings) ? inputs.action_bindings : [];
  if (!bindings.length) throw new Error("Compute task must declare action bindings");
  const bindingNames = bindings.map((item) => item.name);
  const declaredNames = [...inputs.required_actions, ...inputs.optional_actions];
  if (JSON.stringify(bindingNames) !== JSON.stringify(declaredNames)) {
    throw new Error("Compute task action bindings do not match its declared action plan");
  }
  if (!inputs.primary_action || !bindingNames.includes(inputs.primary_action)) {
    throw new Error("Compute task primary_action must be one of its declared actions");
  }
  const expectedCapabilities = [...bindings.map((action) => action.tool), COMPUTE_RESULT_TOOL_NAME];
  if (JSON.stringify(task.capabilities) !== JSON.stringify(expectedCapabilities)) {
    throw new Error("Compute task capabilities do not match its declared action plan");
  }
  const bytes = Buffer.byteLength(serializeAgentDocument(task), "utf8");
  if (bytes > MAX_COMPUTE_TASK_BYTES) {
    throw new Error(`Compute task exceeds ${MAX_COMPUTE_TASK_BYTES} bytes`);
  }
  return task;
}

function normalizeCapabilityDescriptor(value, capability, version) {
  if (!isPlainObject(value)) throw new Error("Compute task requires a capability descriptor summary");
  const allowed = ["capability", "version", "input_roles", "output_roles", "parsers", "operations", "actions", "action_plan"];
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length) throw new Error(`capability descriptor contains unknown fields: ${unknown.join(", ")}`);
  if (value.capability !== capability || value.version !== version) {
    throw new Error("capability descriptor does not match the requested capability");
  }
  return {
    capability: requirePattern(
      value.capability,
      "capabilityDescriptor.capability",
      /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/,
      128,
    ),
    version: requirePattern(value.version, "capabilityDescriptor.version", /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/, 32),
    input_roles: uniqueStrings(value.input_roles, "capabilityDescriptor.input_roles", 32, 64),
    output_roles: uniqueStrings(value.output_roles, "capabilityDescriptor.output_roles", 32, 64),
    parsers: uniqueStrings(value.parsers, "capabilityDescriptor.parsers", 16, 128),
    ...(value.operations === undefined ? {} : { operations: uniqueStrings(value.operations, "capabilityDescriptor.operations", 32, 128) }),
    ...(value.actions === undefined ? {} : { actions: uniqueStrings(value.actions, "capabilityDescriptor.actions", 64, 128) }),
    ...(value.action_plan === undefined ? {} : { action_plan: value.action_plan }),
  };
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
  COMPUTE_RESULT_TOOL_NAME,
  MAX_COMPUTE_TASK_BYTES,
  buildComputeTask,
  validateComputeTask,
};
