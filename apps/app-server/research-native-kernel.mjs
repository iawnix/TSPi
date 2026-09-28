import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

import { create_python_kernel_bridge } from "../../packages/research-agent-kernel/python_kernel_bridge.mjs";

/**
 * Route native Research tools through the new filesystem Kernel when the
 * workspace has a Research Agent manifest. Legacy workspaces continue to use
 * the historical ts_api.py path until they are migrated.
 */
export function isFilesystemResearchWorkspace(root) {
  const workspaceRoot = resolve(root);
  return existsSync(join(workspaceRoot, "research_map", "context.json"))
    || existsSync(join(workspaceRoot, "lifecycle", "liveness.json"));
}

export async function executeFilesystemResearchCommand(command, root, params = {}) {
  const workspaceRoot = resolve(root);
  const bridge = create_python_kernel_bridge({ workspace_root: workspaceRoot });
  try {
    const request = params.request && typeof params.request === "object"
      ? params.request
      : params;
    if (command === "research.context") return await bridge.read_context(request);
    if (command === "research.liveness") return await bridge.read_liveness(request);
    if (command === "research.change") return await bridge.apply_change(request);
    if (command === "research.strategy") return await applyDecisionChange(bridge, request, "strategy");
    if (command === "research.interpretation") return await applyDecisionChange(bridge, request, "interpretation");
    if (command === "research.checkpoint") {
      const checkpoint = await bridge.checkpoint(request);
      const liveness = await bridge.read_liveness(request);
      return { ...checkpoint, lifecycle: liveness.lifecycle, disposition: liveness.disposition ?? null, liveness };
    }
    if (command === "research.turn") {
      const turn = await bridge.turn(request);
      if (request.operation !== "checkpoint") return turn;
      const liveness = await bridge.read_liveness(request);
      return { ...turn, lifecycle: liveness.lifecycle, disposition: liveness.disposition ?? null, liveness };
    }
    if (command === "research.map" || command === "research.summary") {
      const context = await bridge.read_context(request);
      return researchSummary(context, command === "research.map" ? "map" : "summary");
    }
    if (command === "research.detail") {
      const context = await bridge.read_context(request);
      return researchDetail(context, params.kind, params.id);
    }
    if (command === "research.decisions") {
      const context = await bridge.read_context(request);
      return researchDecisions(context, params.claimId || params.claim_id);
    }
    if (command === "research.evidence") {
      const context = await bridge.read_context(request);
      return researchEvidence(context, params);
    }
    if (command === "research.storage") {
      const context = await bridge.read_context(request);
      return {
        schema_version: "research-storage/1",
        backend: "filesystem",
        sqlite: false,
        path: join(workspaceRoot, "research_map", "context.json"),
        revision: context.revision,
      };
    }
    if (command === "research.validate") {
      const context = await bridge.read_context(request);
      return { schema_version: "research-validation/1", valid: true, revision: context.revision };
    }
    if (command === "research.operations") {
      return {
        schema_version: "research-operation-catalog/1",
        operations: [
          "create_phase", "create_claim", "create_node", "set_focus",
          "set_node_state", "set_claim_status", "relate_claims",
          "set_continuation", "resolve_continuation",
          "create_finding", "create_gate", "evaluate_gate", "create_artifact",
          "create_attempt", "transition_attempt", "create_evidence",
          "create_strategy_plan", "create_strategy_review", "create_interpretation",
        ],
      };
    }
    if (command === "research.continuation") {
      if (!request.operation || request.operation === "status") {
        const context = await bridge.read_context(request);
        return continuationStatus(context);
      }
      const contextBefore = await bridge.read_context(request);
      const operation = continuationOperation(request, contextBefore);
      const commit = await bridge.apply_change({
        ...request,
        operations: [operation],
      });
      const context = await bridge.read_context(request);
      return {
        schema_version: "research-continuation-result/1",
        operation: request.operation,
        commit,
        ...continuationStatus(context),
      };
    }
    throw new Error(`unsupported filesystem research command: ${command}`);
  } finally {
    await bridge.close();
  }
}

function continuationStatus(context) {
  const records = Array.isArray(context?.continuations)
    ? context.continuations.filter((item) => item && typeof item === "object")
    : [];
  const groups = Object.fromEntries(["required", "deferred", "blocked", "completed"]
    .map((status) => [status, records.filter((item) => item.status === status)]));
  return {
    schema_version: "research-continuation-status/1",
    continuations: records,
    ...groups,
    waiting_external: [],
  };
}

function continuationOperation(request, context) {
  const operation = request.operation;
  const status = operation === "set_deferred" || operation === "set_blocked"
    ? operation.slice(4)
    : operation === "set_completed" ? "completed"
      : operation === "set_required" ? "required"
        : (operation === "resolve" || operation === "clear")
          ? request.status || "completed"
          : request.status || "required";
  if (!["set", "set_required", "set_deferred", "set_blocked", "set_completed", "resolve", "clear"].includes(operation)) {
    throw new Error("continuation operation must be status, set, resolve, or a supported set_* alias");
  }
  if (!["required", "deferred", "blocked", "completed"].includes(status)) {
    throw new Error("continuation status must be required, deferred, blocked, or completed");
  }
  let continuationId = request.continuation_id || request.id;
  const records = Array.isArray(context?.continuations) ? context.continuations : [];
  const hasTarget = request.scope !== undefined || request.target_id !== undefined || request.action !== undefined;
  if (["set_deferred", "set_blocked", "set_completed"].includes(operation) && !continuationId && hasTarget) {
    const candidates = records.filter((item) => item?.status === "required"
      && item.scope === request.scope
      && (item.target_id === request.target_id || item.target_ref === request.target_id)
      && (request.action === undefined || item.action === request.action));
    if (candidates.length === 1) continuationId = candidates[0].id;
    if (candidates.length > 1) throw new Error("continuation disposition is ambiguous; provide continuationId");
  }
  const shouldResolve = operation === "resolve" || operation === "clear"
    || Boolean(continuationId && ["set", "set_required", "set_deferred", "set_blocked", "set_completed"].includes(operation));
  if (shouldResolve) {
    if (typeof continuationId !== "string" || continuationId.length === 0) {
      throw new Error(`research_continuation ${operation} requires continuationId`);
    }
    const existing = records.find((item) => item?.id === continuationId);
    if (!existing) throw new Error(`unknown continuation ${continuationId}`);
    for (const [field, expected] of [["scope", existing.scope], ["target_id", existing.target_id], ["action", existing.action]]) {
      if (request[field] !== undefined && request[field] !== expected) {
        throw new Error(`continuation ${continuationId} ${field} does not match the existing record`);
      }
    }
    return {
      type: "resolve_continuation",
      id: continuationId,
      status: operation === "clear" ? "completed" : status,
      ...(request.reason === undefined ? {} : { reason: request.reason }),
      ...(request.request_id === undefined ? {} : { request_id: request.request_id }),
    };
  }
  if (typeof request.scope !== "string" || typeof request.target_id !== "string" || typeof request.action !== "string") {
    throw new Error(`research_continuation ${operation} requires scope, targetId, and action`);
  }
  const id = continuationId || `continuation_${request.scope}_${request.target_id}_${request.action}`;
  return {
    type: "set_continuation",
    id,
    scope: request.scope,
    target_id: request.target_id,
    action: request.action,
    status,
    ...(request.reason === undefined ? {} : { reason: request.reason }),
    ...(request.request_id === undefined ? {} : { request_id: request.request_id }),
  };
}

async function applyDecisionChange(bridge, request, kind) {
  // Tool aliases normally provide `plan`/`review`, but older Root Agent
  // turns sent the operation payload under the operation name. Normalize both
  // forms at this boundary so schema drift does not become a misleading
  // "requires a decision object" failure.
  const source = kind === "strategy"
    ? request[request.operation] || request.plan || request.review || request.strategy
    : request.interpretation;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    throw new Error(`research.${kind} requires a decision object`);
  }
  const operation = kind === "strategy"
    ? (request.operation === "review" ? "create_strategy_review" : "create_strategy_plan")
    : "create_interpretation";
  const result = await bridge.apply_change({
    ...request,
    operations: [{ type: operation, ...source }],
  });
  return {
    schema_version: kind === "strategy" ? "research-strategy-result/1" : "research-interpretation-result/1",
    operation: request.operation || kind,
    record: source,
    commit: result,
  };
}

function collection(context, kind) {
  const names = {
    phase: "phases",
    claim: "claims",
    node: "nodes",
    finding: "findings",
    gate: "gates",
    strategy: "strategy_plans",
    review: "strategy_reviews",
    interpretation: "attempt_interpretations",
    attempt: "attempts",
    artifact: "artifacts",
    evidence: "evidence_links",
  };
  return Array.isArray(context?.[names[kind]]) ? context[names[kind]] : [];
}

function researchSummary(context, mode) {
  return {
    schema_version: "research-summary/1",
    mode,
    workspace_id: context.workspace_id,
    workspace_mode: context.workspace_mode,
    revision: context.revision,
    lifecycle_state: context.lifecycle_state,
    phases: collection(context, "phase"),
    claims: collection(context, "claim"),
    nodes: collection(context, "node"),
    findings: collection(context, "finding"),
    gates: collection(context, "gate"),
    focus: context.focus || { claim_ids: [], node_ids: [] },
  };
}

function researchDetail(context, kind, id) {
  const item = collection(context, kind).find((row) => row?.id === id);
  if (!item) throw new Error(`research detail not found: ${kind}/${id}`);
  return { schema_version: "research-detail/1", kind, id, item };
}

function researchDecisions(context, claimId) {
  const rows = [
    ...collection(context, "strategy").map((item) => ({ ...item, decision_type: "strategy_plan" })),
    ...collection(context, "review").map((item) => ({ ...item, decision_type: "strategy_review" })),
    ...collection(context, "interpretation").map((item) => ({ ...item, decision_type: "attempt_interpretation" })),
  ].filter((item) => claimId === undefined || item.claim_id === claimId);
  return { schema_version: "research-decisions/1", claim_id: claimId || null, records: rows };
}

function researchEvidence(context, params) {
  const kind = params.recordType || params.record_type;
  const groups = kind ? [kind] : ["attempt", "artifact", "evidence"];
  const rows = groups.flatMap((name) => collection(context, name));
  return {
    schema_version: "research-evidence/1",
    record_type: kind || null,
    records: rows,
  };
}
