import { lstatSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { create_python_kernel_bridge } from "../../packages/research-state-bridge/python_kernel_bridge.mjs";

/**
 * Route native Research tools through the new filesystem Kernel when the
 * workspace has the complete canonical manifest/state tuple. Partial or
 * legacy layouts are rejected by the public Python command boundary rather
 * than silently selecting a second ResearchMap authority.
 */
export function isFilesystemResearchWorkspace(root) {
  const workspaceRoot = resolve(root);
  const manifestPath = join(workspaceRoot, "workspace_manifest.json");
  if (!isPhysicalFile(manifestPath)
    || !isPhysicalFile(join(workspaceRoot, "research_map", "context.json"))
    || !isPhysicalFile(join(workspaceRoot, "lifecycle", "liveness.json"))) return false;
  try {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    return manifest?.schema_version === "research_state_workspace_1"
      && manifest.workspace_mode === "research"
      && manifest.state === "ready";
  } catch {
    return false;
  }
}

function isPhysicalFile(path) {
  try {
    const stat = lstatSync(path);
    return stat.isFile() && !stat.isSymbolicLink();
  } catch {
    return false;
  }
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
    if (command === "research.locate") {
      const context = await bridge.read_context(request);
      return researchLocate(context, params.query);
    }
    if (command === "research.decisions") {
      const context = await bridge.read_context(request);
      return researchDecisions(context, params.claimId || params.claim_id, params.limit);
    }
    if (command === "research.evidence") {
      const context = await bridge.read_context(request);
      return researchEvidence(context, params);
    }
    if (command === "research.storage") {
      if (params.operation !== undefined && params.operation !== "status") {
        throw new Error("research.storage supports only operation=status");
      }
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
      return researchOperationCatalog();
    }
    throw new Error(`unsupported filesystem research command: ${command}`);
  } finally {
    await bridge.close();
  }
}

// Keep the Native route's read model identical to
// tspi_runtime.workspace.operation_registry.operation_catalog().  The catalog is
// descriptive only; all writes still cross the Kernel change boundary.
function researchOperationCatalog() {
  const contracts = [
    ["create_claim", ["id", "statement", "type"], ["created_at", "falsifiers", "metadata", "predictions", "status"]],
    ["create_finding", ["id", "kind", "node_id", "statement", "type"], ["claim_ids", "created_at", "datatype", "metadata", "provenance", "resolution", "severity", "source_refs", "status", "unit", "value"]],
    ["create_gate", ["id", "scope", "target_id", "type"], ["created_at", "criteria", "metadata"]],
    ["create_node", ["id", "objective", "title", "type"], ["claim_ids", "created_at", "dependency_ids", "metadata", "phase_id"]],
    ["create_phase", ["id", "title", "type"], ["created_at", "metadata", "objective"]],
    ["resolve_lifecycle_action", ["id", "status", "type"], ["reason", "request_id"]],
    ["set_lifecycle_action", ["action", "id", "scope", "target_id", "type"], ["created_at", "metadata", "reason", "request_id", "status"]],
    ["evaluate_gate", ["gate_id", "type", "verdict"], ["created_at", "evidence_refs", "message"]],
    ["relate_claims", ["relation", "source_id", "target_id", "type"], []],
    ["set_claim_status", ["claim_id", "status", "type"], []],
    ["set_focus", ["claim_ids", "node_ids", "type"], []],
    ["set_node_state", ["node_id", "state", "type"], ["outcome", "summary"]],
  ];
  return {
    schema_version: "research-operation-catalog/1",
    selected_operation: null,
    operations: contracts.map(([type, required_fields, optional_fields]) => ({
      type, required_fields, optional_fields,
    })),
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
  if (mode === "map") return researchMapDocument(context);
  const phases = collection(context, "phase");
  const claims = collection(context, "claim");
  const nodes = collection(context, "node");
  const findings = collection(context, "finding");
  const gates = collection(context, "gate");
  return {
    schema_version: "research-summary/1",
    mode,
    map_id: typeof context?.map_id === "string" && context.map_id.length
      ? context.map_id : `map_${context.workspace_id}`,
    workspace_id: context.workspace_id,
    workspace_mode: context.workspace_mode,
    revision: context.revision,
    lifecycle_state: context.lifecycle_state,
    phases,
    claims,
    nodes,
    findings,
    gates,
    focus: context.focus || { claim_ids: [], node_ids: [] },
    progress: {
      phase_count: phases.length,
      claim_count: claims.length,
      node_count: nodes.length,
      finding_count: findings.length,
      gate_count: gates.length,
      closed_node_count: nodes.filter((item) => item?.state === "closed").length,
      open_issue_count: findings.filter((item) => item?.kind === "issue" && item?.status === "open").length,
    },
  };
}

function researchMapDocument(context) {
  const focus = context?.focus && typeof context.focus === "object" ? context.focus : {};
  const mapId = typeof context?.map_id === "string" && context.map_id.length
    ? context.map_id : `map_${context.workspace_id}`;
  const createdAt = typeof context?.created_at === "string" && context.created_at.length
    ? context.created_at : null;
  if (!createdAt) throw new Error("ResearchMap created_at is invalid");
  const collections = [
    "phases", "claims", "nodes", "findings", "gates", "lifecycle_actions", "claim_relations",
  ];
  for (const name of collections) {
    if (!Array.isArray(context?.[name])) throw new Error(`ResearchMap ${name} must be an array`);
  }
  if (!Array.isArray(focus.claim_ids) || !Array.isArray(focus.node_ids)) {
    throw new Error("ResearchMap focus is invalid");
  }
  const nodes = context.nodes;
  const findings = context.findings;
  return {
    schema_version: "research-map/1",
    map_id: mapId,
    title: typeof context?.title === "string" && context.title.length
      ? context.title : context.workspace_id,
    created_at: createdAt,
    revision: context.revision,
    phases: context.phases,
    claims: context.claims,
    nodes,
    findings,
    gates: context.gates,
    lifecycle_actions: context.lifecycle_actions,
    claim_relations: context.claim_relations,
    focus_claim_ids: [...focus.claim_ids],
    focus_node_ids: [...focus.node_ids],
    metadata: context.metadata && typeof context.metadata === "object" ? context.metadata : {},
    progress: {
      phase_count: context.phases.length,
      claim_count: context.claims.length,
      node_count: nodes.length,
      finding_count: findings.length,
      gate_count: context.gates.length,
      closed_node_count: nodes.filter((item) => item?.state === "closed").length,
      open_issue_count: findings.filter((item) => item?.kind === "issue" && item?.status === "open").length,
    },
  };
}

function researchDetail(context, kind, id) {
  const item = collection(context, kind).find((row) => row?.id === id);
  if (!item) throw new Error(`research detail not found: ${kind}/${id}`);
  return { schema_version: "research-detail/1", kind, id, item };
}

function researchDecisions(context, claimId, limit = 128) {
  const rows = [
    ...collection(context, "strategy").map((item) => ({ ...item, decision_type: "strategy_plan" })),
    ...collection(context, "review").map((item) => ({ ...item, decision_type: "strategy_review" })),
    ...collection(context, "interpretation").map((item) => ({ ...item, decision_type: "attempt_interpretation" })),
  ].filter((item) => claimId === undefined || item.claim_id === claimId);
  const bounded = Number.isSafeInteger(limit) && limit >= 1 && limit <= 2048 ? limit : 128;
  return { schema_version: "research-decisions/1", claim_id: claimId || null, records: rows.slice(0, bounded) };
}

function researchEvidence(context, params) {
  const requestedKind = params.recordType || params.record_type;
  if (requestedKind !== undefined && !["attempt", "artifact", "link"].includes(requestedKind)) {
    throw new Error("research.evidence record_type must be attempt, artifact, or link");
  }
  const kind = requestedKind === "link" ? "evidence" : requestedKind;
  const groups = kind ? [kind] : ["attempt", "artifact", "evidence"];
  let rows = groups.flatMap((name) => collection(context, name));
  const filters = {
    node_id: params.nodeId || params.node_id,
    artifact_id: params.artifactId || params.artifact_id,
    subject_id: params.subjectId || params.subject_id,
  };
  for (const [field, expected] of Object.entries(filters)) {
    if (expected === undefined) continue;
    rows = rows.filter((item) => item?.[field] === expected
      || item?.subject?.[field] === expected
      || (Array.isArray(item?.[`${field}s`]) && item[`${field}s`].includes(expected)));
  }
  const limit = Number.isSafeInteger(params.limit) && params.limit >= 1 && params.limit <= 2048
    ? params.limit : 128;
  return {
    schema_version: "research-evidence/1",
    record_type: requestedKind || null,
    records: rows.slice(0, limit),
  };
}

function researchLocate(context, query) {
  if (typeof query !== "string" || query.trim() === "") {
    throw new Error("research.locate query must be a non-empty string");
  }
  const needle = query.toLocaleLowerCase();
  const matches = [];
  for (const name of ["phases", "claims", "nodes", "findings", "gates"]) {
    const items = Array.isArray(context?.[name]) ? context[name] : [];
    for (const item of items) {
      if (JSON.stringify(item).toLocaleLowerCase().includes(needle)) {
        const kind = name.slice(0, -1);
        matches.push({ ...item, collection: kind, object_type: item?.type || kind });
      }
    }
  }
  const mapId = typeof context?.map_id === "string" && context.map_id.length
    ? context.map_id : `map_${context.workspace_id}`;
  return { schema_version: "research-locate/1", map_id: mapId, matches };
}
