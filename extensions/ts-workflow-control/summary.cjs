"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = [
  "research_state.json",
  "evidence_registry.json",
  "hypotheses.json",
];

function normalizePath(value, cwd = process.cwd()) {
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  const stripped = value.trim().replace(/^@+/, "");
  return path.resolve(cwd, stripped);
}

function isWorkspaceRoot(root) {
  return WORKSPACE_MARKERS.every((name) => fs.existsSync(path.join(root, name)));
}

function findWorkspaceRoot(start = process.cwd(), env = process.env) {
  const explicit = normalizePath(env.TS_WORKSPACE_ROOT || "", start);
  if (explicit && isWorkspaceRoot(explicit)) {
    return explicit;
  }

  let current = path.resolve(start);
  while (true) {
    if (isWorkspaceRoot(current)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

function resolveWorkspaceRoot(inputRoot, cwd = process.cwd(), env = process.env) {
  const explicit = normalizePath(inputRoot || "", cwd);
  if (explicit) {
    return explicit;
  }
  return findWorkspaceRoot(cwd, env);
}

function buildContextDetails(report) {
  const focus = objectOrEmpty(report.focus);
  const hypothesisContext = objectOrEmpty(report.hypothesis_context);
  const activeHypothesis = objectOrEmpty(hypothesisContext.active_hypothesis);
  const openNodes = arrayOfObjects(report.open_nodes);
  const branchEvents = arrayOfObjects(report.branch_events);
  const branchFrontiers = arrayOfObjects(report.branch_frontiers);
  const operationalSummary = objectOrEmpty(report.operational_summary);
  const agentRuns = arrayOfObjects(report.agent_runs);
  const pendingControls = arrayOfObjects(report.pending_controls);
  const unresolvedControls = arrayOfObjects(report.unresolved_controls);

  return {
    reportId: report.report_id || "",
    workspaceId: report.workspace_id || "",
    workspaceRevision: report.workspace_revision || "",
    operationalRevision: report.operational_revision || "",
    workspaceRoot: report.workspace_root || "",
    valid: Boolean(report.valid),
    validationFindings: arrayOfObjects(report.validation_findings).map((item) => ({
      severity: item.severity || "",
      code: item.code || "",
      message: item.message || "",
      path: item.path || "",
    })),
    currentNode: focus.current_node || null,
    focusPathwayId: focus.focus_pathway_id || null,
    focusHypothesisId: focus.focus_hypothesis_id || hypothesisContext.focus_hypothesis_id || null,
    acceptedTsRefs: arrayOfStrings(focus.accepted_ts_refs),
    openNodes: openNodes.map((node) => ({
      nodeId: node.node_id || "",
      nodeType: node.node_type || node.phase || "",
      scope: node.validation_scope || node.audit_scope || node.candidate_kind || node.mechanism_action || "",
      lifecycle: node.lifecycle || "",
      objective: node.objective || node.hypothesis || "",
    })),
    closedNodeCount: numberOrZero(report.closed_node_count),
    evidenceCount: numberOrZero(report.evidence_count),
    operationalSummary: {
      trackedFileCount: numberOrZero(operationalSummary.tracked_file_count),
      calculationFileCount: numberOrZero(operationalSummary.calculation_file_count),
      agentRunCount: numberOrZero(operationalSummary.agent_run_count),
      agentRunFailedCount: numberOrZero(operationalSummary.agent_run_failed_count),
      agentRunPendingCount: numberOrZero(operationalSummary.agent_run_pending_count),
      controlPendingCount: numberOrZero(operationalSummary.control_pending_count),
      controlUnresolvedCount: numberOrZero(operationalSummary.control_unresolved_count),
      ambiguousSubmissionCount: numberOrZero(operationalSummary.ambiguous_submission_count),
      ambiguousCancellationCount: numberOrZero(operationalSummary.ambiguous_cancellation_count),
      controlRetryableCount: numberOrZero(operationalSummary.control_retryable_count),
    },
    pendingControls: pendingControls.map((control) => ({
      operation: control.operation || "",
      intentId: control.intent_id || "",
      guardRef: control.guard_ref || "",
    })),
    unresolvedControls: unresolvedControls.map((control) => ({
      operation: control.operation || "",
      intentId: control.intent_id || "",
      state: control.state || "",
      errorClass: control.error_class || "",
      retryDisposition: control.retry_disposition || "",
      resultRef: control.result_ref || "",
    })),
    latestAgentRuns: agentRuns.slice(-5).map((run) => ({
      taskId: run.task_id || "",
      role: run.role || "",
      operation: run.operation || "",
      status: run.status || "",
      runRef: run.run_ref || "",
    })),
    hypothesisSummary: activeHypothesis.summary || "",
    openPredictions: arrayOfObjects(hypothesisContext.open_predictions).map((prediction) => ({
      predictionId: prediction.prediction_id || "",
      scope: prediction.validation_scope || prediction.phase || "",
      expectation: prediction.expectation || "",
    })),
    supportedPredictions: arrayOfStrings(hypothesisContext.supported_predictions),
    refutedPredictions: arrayOfStrings(hypothesisContext.refuted_predictions),
    requiredNextEvidence: arrayOfStrings(hypothesisContext.required_next_evidence),
    branchEvents: branchEvents.map((event) => ({
      relation: event.relation || "",
      fromNode: event.from_node || "",
      anchorNode: event.anchor_node || "",
      newNode: event.new_node || "",
      changedVariable: event.changed_variable || "",
      reasonCode: event.reason_code || "",
    })),
    branchFrontiers: branchFrontiers.map((node) => ({
      nodeId: node.node_id || "",
      nodeType: node.node_type || node.phase || "",
      scope: node.scope || "",
      lifecycle: node.lifecycle || "",
      claimVerdict: node.claim_verdict || "",
      programStatus: node.program_status || "",
      hypothesisStatus: node.hypothesis_status || "",
      programOutcome: node.program_outcome || "",
      auditStatus: node.audit_status || "",
      hasOutgoingBranch: Boolean(node.has_outgoing_branch),
    })),
    allowedDecisionActions: arrayOfStrings(report.allowed_decision_actions),
  };
}

function buildContextSummary(report, options = {}) {
  const details = buildContextDetails(report);
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 5;
  const lines = [
    "TS workspace context:",
    `- workspace: ${details.workspaceRoot || "(unknown)"}; compute_workspace_id: ${details.workspaceId || "(missing)"}`,
    `- report: ${details.reportId || "(none)"}; revision: ${details.workspaceRevision || "(none)"}; valid: ${details.valid}`,
    `- operational_revision: ${details.operationalRevision || "(none)"}; calculations=${details.operationalSummary.calculationFileCount}; agent_runs=${details.operationalSummary.agentRunCount}; failed=${details.operationalSummary.agentRunFailedCount}; pending=${details.operationalSummary.agentRunPendingCount}; pending_controls=${details.operationalSummary.controlPendingCount}; unresolved_controls=${details.operationalSummary.controlUnresolvedCount}; ambiguous_submissions=${details.operationalSummary.ambiguousSubmissionCount}; ambiguous_cancellations=${details.operationalSummary.ambiguousCancellationCount}; retryable_controls=${details.operationalSummary.controlRetryableCount}`,
    `- current_node: ${details.currentNode || "(none)"}; focus_hypothesis: ${details.focusHypothesisId || "(none)"}`,
    `- focus_pathway: ${details.focusPathwayId || "(none)"}; accepted_ts_refs: ${formatList(details.acceptedTsRefs, maxItems)}`,
    `- open_nodes: ${details.openNodes.length ? details.openNodes.map(formatNode).join("; ") : "(none)"}`,
    `- counts: closed_nodes=${details.closedNodeCount}; evidence=${details.evidenceCount}`,
  ];

  if (details.hypothesisSummary) {
    lines.push(`- active_hypothesis: ${details.hypothesisSummary}`);
  }
  if (details.pendingControls.length) {
    lines.push(`- pending_controls: ${details.pendingControls.map((item) => `${item.operation}:${item.intentId}`).join(", ")}`);
  }
  if (details.unresolvedControls.length) {
    lines.push(`- unresolved_controls: ${details.unresolvedControls.map((item) => `${item.operation}:${item.intentId}:${item.errorClass || item.state || "unknown"}`).join(", ")}`);
  }
  lines.push(`- open_predictions: ${formatPredictionList(details.openPredictions, maxItems)}`);
  lines.push(`- supported_predictions: ${formatList(details.supportedPredictions, maxItems)}`);
  lines.push(`- refuted_predictions: ${formatList(details.refutedPredictions, maxItems)}`);
  lines.push(`- required_next_evidence: ${formatList(details.requiredNextEvidence, maxItems)}`);
  lines.push(`- branch_events: ${formatBranchList(details.branchEvents, maxItems)}`);
  lines.push(`- history_checkpoints: ${formatCheckpointList(details.branchFrontiers, maxItems)}`);
  lines.push(`- allowed_decision_actions: ${formatList(details.allowedDecisionActions, maxItems)}`);
  if (details.latestAgentRuns.length) {
    lines.push(`- latest_agent_runs: ${details.latestAgentRuns.map(formatAgentRun).join(", ")}`);
  }

  if (details.validationFindings.length) {
    lines.push(
      `- validation_findings: ${details.validationFindings
        .slice(0, maxItems)
        .map((finding) => `${finding.code || "finding"}:${finding.message || finding.path || ""}`)
        .join("; ")}`
    );
  }

  lines.push(
    "- contract: use ts_workspace_context/ts_workspace_decision_draft/ts_workspace_decision_validate/ts_workspace_decision_apply; do not edit workspace state files by hand; shell fallbacks must use an explicit TSAgentSkill root, not cwd-relative scripts."
  );
  lines.push("- contract: n000 is intake; only mechanism nodes set hypothesis status; candidate and validation nodes return program facts and evidence only.");
  return lines.join("\n");
}

function buildNodeContextSummary(context, options = {}) {
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 8;
  const node = objectOrEmpty(context.node);
  const hypothesis = objectOrEmpty(context.hypothesis);
  const pathway = objectOrEmpty(context.pathway);
  const artifactRefs = objectOrEmpty(context.artifact_refs);
  const nodeArtifacts = objectOrEmpty(artifactRefs.node_artifacts);
  const evidence = arrayOfObjects(context.evidence);
  const events = arrayOfObjects(context.branch_events);
  const decisions = arrayOfObjects(context.decisions);
  const agentRuns = arrayOfObjects(context.agent_runs);
  const lines = [
    "TS historical node context:",
    `- node: ${node.node_id || "?"}; type=${node.node_type || node.phase || "?"}; scope=${node.validation_scope || node.audit_scope || node.candidate_kind || node.mechanism_action || "(none)"}; lifecycle=${node.lifecycle || "?"}`,
    `- parent: ${node.parent_node || "(none)"}; lineage: ${formatList(arrayOfStrings(context.lineage), maxItems)}`,
    `- program: ${node.program_outcome || node.program_status || "(none)"}; hypothesis_status: ${node.hypothesis_status || node.claim_verdict || "(none)"}; audit_status: ${node.audit_status || "(none)"}`,
    `- objective: ${node.objective || node.hypothesis || "(none)"}`,
    `- program_summary: ${node.program_summary || "(none)"}`,
    `- program_facts: ${formatAnyList(node.program_facts, maxItems)}`,
    `- mechanism_summary: ${node.mechanism_summary || "(none)"}`,
    `- mechanism_facts: ${formatAnyList(node.mechanism_facts, maxItems)}`,
    `- implication: ${node.implication || "(none)"}`,
    `- open_questions: ${formatAnyList(node.open_questions, maxItems)}`,
    `- active_hypothesis_record: ${hypothesis.hypothesis_id || "(none)"}/${hypothesis.status || "(none)"}; ${hypothesis.summary || ""}`,
    `- pathway_record: ${pathway.pathway_id || "(none)"}/${pathway.status || "(none)"}; ${pathway.pattern || ""}`,
    `- evidence: ${formatEvidenceList(evidence, maxItems)}`,
    `- artifact_paths: ${formatArtifactPaths(nodeArtifacts)}`,
    `- evidence_paths: ${formatList(arrayOfStrings(artifactRefs.evidence_paths), maxItems)}`,
    `- source_files: ${formatList(arrayOfStrings(artifactRefs.source_files), maxItems)}`,
    `- branch_events: ${formatBranchList(events.map(normalizeBranchEvent), maxItems)}`,
    `- decisions: ${decisions.slice(0, maxItems).map((item) => `${item.decision_id || "?"}:${item.action || "?"}:${item.rationale || ""}`).join("; ") || "(none)"}`,
    `- agent_runs: ${agentRuns.slice(-maxItems).map((item) => `${item.task_id || "?"}:${item.role || "?"}/${item.operation || "?"}/${item.status || "?"}`).join("; ") || "(none)"}`,
    "- contract: this node is immutable historical evidence; inspecting it does not select a branch or mutate the workspace.",
  ];
  return lines.join("\n");
}

function buildBranchContextSummary(context, options = {}) {
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 8;
  const fromContext = objectOrEmpty(context.from_node);
  const anchorContext = objectOrEmpty(context.anchor_node);
  const fromNode = objectOrEmpty(fromContext.node);
  const anchorNode = objectOrEmpty(anchorContext.node);
  const pathDelta = arrayOfObjects(context.path_delta);
  return [
    "TS backtrack context:",
    `- trigger: ${formatNodeState(fromNode)}`,
    `- selected_checkpoint: ${formatNodeState(anchorNode)}`,
    `- checkpoint_summary: ${anchorNode.mechanism_summary || anchorNode.hypothesis || "(none)"}`,
    `- trigger_summary: ${fromNode.mechanism_summary || fromNode.program_summary || "(none)"}`,
    `- attempted_since_checkpoint: ${pathDelta.slice(0, maxItems).map(formatNodeDelta).join("; ") || "(none)"}`,
    "- contract: the agent must choose relation, parent, hypothesis, solution, and pathway after reviewing this context; tooling only validates the resulting topology.",
  ].join("\n");
}

function parseJsonOutput(result) {
  if (result && typeof result === "object") {
    for (const key of ["stdout", "output", "text"]) {
      if (typeof result[key] === "string" && result[key].trim()) {
        return JSON.parse(result[key]);
      }
    }
  }
  if (typeof result === "string" && result.trim()) {
    return JSON.parse(result);
  }
  if (result && typeof result === "object" && typeof result.stderr === "string" && result.stderr.trim()) {
    const stderr = result.stderr.trim();
    let payload;
    try {
      payload = JSON.parse(stderr);
    } catch (_error) {
      payload = undefined;
    }
    if (payload && typeof payload === "object" && typeof payload.error === "string" && payload.error.trim()) {
      throw new Error(payload.error.trim());
    }
    throw new Error(stderr);
  }
  throw new Error("command result did not contain JSON stdout");
}

function toolText(text, details = {}) {
  return { content: [{ type: "text", text }], details };
}

function formatNode(node) {
  const scope = node.scope ? `:${node.scope}` : "";
  return `${node.nodeId || "node"}:${node.nodeType || "type"}${scope}/${node.lifecycle || "state"}`;
}

function formatAgentRun(run) {
  return `${run.taskId || "run"}:${run.role || "role"}/${run.operation || "operation"}/${run.status || "status"}`;
}

function formatPredictionList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  return values
    .slice(0, maxItems)
    .map((item) => `${item.predictionId || "prediction"}:${item.scope || "scope"}`)
    .join(", ");
}

function formatBranchList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  return values
    .slice(-maxItems)
    .map((item) => `${item.fromNode || "?"}->${item.newNode || "?"}:${item.relation || item.changedVariable || item.reasonCode || "branch"}`)
    .join(", ");
}

function formatCheckpointList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  const unused = values.filter((item) => !item.hasOutgoingBranch).slice(-maxItems);
  const remaining = Math.max(0, maxItems - unused.length);
  const used = remaining ? values.filter((item) => item.hasOutgoingBranch).slice(-remaining) : [];
  const candidates = unused.concat(used);
  return candidates
    .map((item) => `${item.nodeId || "?"}:${item.nodeType || "?"}${item.scope ? `:${item.scope}` : ""}/${item.programOutcome || item.programStatus || item.lifecycle || "?"}/${item.hypothesisStatus || item.auditStatus || item.claimVerdict || "?"}`)
    .join(", ");
}

function formatEvidenceList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  return values
    .slice(0, maxItems)
    .map((item) => `${item.evidence_id || "?"}/${item.role || item.kind || "evidence"}: ${item.summary || ""}`)
    .join("; ");
}

function formatArtifactPaths(value) {
  const entries = ["inputs", "outputs", "remote", "scratch"]
    .filter((key) => typeof value[key] === "string" && value[key].trim())
    .map((key) => `${key}=${value[key]}`);
  return entries.join(", ") || "(none)";
}

function normalizeBranchEvent(event) {
  return {
    relation: event.relation || "",
    fromNode: event.from_node || "",
    anchorNode: event.anchor_node || "",
    newNode: event.new_node || "",
    changedVariable: event.changed_variable || "",
    reasonCode: event.reason_code || "",
  };
}

function formatNodeDelta(node) {
  return `${formatNodeState(node)}:${node.mechanism_summary || node.program_summary || node.objective || ""}`;
}

function formatNodeState(node) {
  const type = node.node_type || node.phase || "?";
  const scope = node.validation_scope || node.audit_scope || node.candidate_kind || node.mechanism_action || "";
  const program = node.program_outcome || node.program_status || node.lifecycle || "?";
  const science = node.hypothesis_status || node.audit_status || node.claim_verdict || "?";
  return `${node.node_id || "?"}:${type}${scope ? `:${scope}` : ""}/${program}/${science}`;
}

function formatList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  const visible = values.slice(0, maxItems);
  const suffix = values.length > visible.length ? ` (+${values.length - visible.length} more)` : "";
  return visible.join(", ") + suffix;
}

function formatAnyList(value, maxItems) {
  if (!Array.isArray(value) || !value.length) {
    return "(none)";
  }
  const visible = value.slice(0, maxItems).map((item) => {
    if (typeof item === "string") {
      return item;
    }
    try {
      return JSON.stringify(item);
    } catch (_error) {
      return String(item);
    }
  });
  const suffix = value.length > visible.length ? ` (+${value.length - visible.length} more)` : "";
  return visible.join("; ") + suffix;
}

function objectOrEmpty(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function arrayOfObjects(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
}

function arrayOfStrings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item.trim()) : [];
}

function numberOrZero(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function main(argv) {
  const reportFlag = argv.indexOf("--report");
  if (reportFlag < 0 || !argv[reportFlag + 1]) {
    console.error("usage: node summary.cjs --report <report.json>");
    return 2;
  }
  const report = JSON.parse(fs.readFileSync(argv[reportFlag + 1], "utf8"));
  const details = buildContextDetails(report);
  const summary = buildContextSummary(report);
  process.stdout.write(JSON.stringify({ summary, details }, null, 2) + "\n");
  return 0;
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = {
  buildBranchContextSummary,
  buildContextDetails,
  buildContextSummary,
  buildNodeContextSummary,
  findWorkspaceRoot,
  isWorkspaceRoot,
  parseJsonOutput,
  resolveWorkspaceRoot,
  toolText,
};
