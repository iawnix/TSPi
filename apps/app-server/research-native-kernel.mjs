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
          "create_finding", "create_gate", "evaluate_gate", "create_artifact",
          "create_attempt", "transition_attempt", "create_evidence",
          "create_strategy_plan", "create_strategy_review", "create_interpretation",
        ],
      };
    }
    if (command === "research.continuation") {
      if (request.operation && request.operation !== "status") {
        throw new Error("research continuation mutations require a durable checkpoint disposition in a Research Agent workspace");
      }
      return {
        schema_version: "research-continuation-status/1",
        required: [],
        continue_required: [],
        deferred: [],
        blocked: [],
        waiting_external: [],
        note: "Research Agent workspaces use durable checkpoint dispositions; legacy continuation records are not projected.",
      };
    }
    throw new Error(`unsupported filesystem research command: ${command}`);
  } finally {
    await bridge.close();
  }
}

async function applyDecisionChange(bridge, request, kind) {
  const source = kind === "strategy" ? request.plan : request.interpretation;
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
