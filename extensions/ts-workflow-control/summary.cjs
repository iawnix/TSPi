"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = [
  "research_state.json",
  "claims.json",
  "evidence_registry.json",
  "gate_results.json",
];

function normalizePath(value, cwd = process.cwd()) {
  if (typeof value !== "string" || !value.trim()) return null;
  return path.resolve(cwd, value.trim().replace(/^@+/, ""));
}

function isWorkspaceRoot(root) {
  return WORKSPACE_MARKERS.every((name) => fs.existsSync(path.join(root, name)));
}

function findWorkspaceRoot(start = process.cwd(), env = process.env) {
  const explicit = normalizePath(env.TS_WORKSPACE_ROOT || "", start);
  if (explicit && isWorkspaceRoot(explicit)) return explicit;
  let current = path.resolve(start);
  while (true) {
    if (isWorkspaceRoot(current)) return current;
    const parent = path.dirname(current);
    if (parent === current) return null;
    current = parent;
  }
}

function resolveWorkspaceRoot(inputRoot, cwd = process.cwd(), env = process.env) {
  return normalizePath(inputRoot || "", cwd) || findWorkspaceRoot(cwd, env);
}

function buildContextDetails(report) {
  const focus = objectOrEmpty(report.focus);
  const operational = objectOrEmpty(report.operational_summary);
  return {
    reportId: report.report_id || "",
    workspaceId: report.workspace_id || "",
    workspaceRevision: report.workspace_revision || "",
    operationalRevision: report.operational_revision || "",
    workspaceRoot: report.workspace_root || "",
    valid: report.valid === true,
    validationFindings: arrayOfObjects(report.validation_findings),
    currentNode: focus.current_node || null,
    openNodeRefs: arrayOfStrings(focus.open_node_refs),
    focusClaimRefs: arrayOfStrings(focus.focus_claim_refs),
    acceptedRefs: arrayOfStrings(focus.accepted_refs),
    focusClaims: arrayOfObjects(report.focus_claims).map((claim) => ({
      claimId: claim.claim_id || "",
      kind: claim.kind || "",
      statement: claim.statement || "",
      status: claim.status || "",
      requiredGates: arrayOfStrings(claim.required_gates),
    })),
    openNodes: arrayOfObjects(report.open_nodes).map((node) => ({
      nodeId: node.node_id || "",
      state: node.state || "",
      tags: arrayOfStrings(node.tags),
      objective: node.objective || "",
    })),
    closedNodeCount: numberOrZero(report.closed_node_count),
    claimCount: numberOrZero(report.claim_count),
    evidenceCount: numberOrZero(report.evidence_count),
    gateResultCount: numberOrZero(report.gate_result_count),
    claimStatusCounts: objectOrEmpty(report.claim_status_counts),
    gateVerdictCounts: objectOrEmpty(report.gate_verdict_counts),
    operationalSummary: {
      trackedFileCount: numberOrZero(operational.tracked_file_count),
      calculationFileCount: numberOrZero(operational.calculation_file_count),
      agentRunCount: numberOrZero(operational.agent_run_count),
      agentRunFailedCount: numberOrZero(operational.agent_run_failed_count),
      agentRunPendingCount: numberOrZero(operational.agent_run_pending_count),
      controlPendingCount: numberOrZero(operational.control_pending_count),
      controlUnresolvedCount: numberOrZero(operational.control_unresolved_count),
      ambiguousSubmissionCount: numberOrZero(operational.ambiguous_submission_count),
      ambiguousCancellationCount: numberOrZero(operational.ambiguous_cancellation_count),
      controlRetryableCount: numberOrZero(operational.control_retryable_count),
      reviewDispositionCount: numberOrZero(operational.review_disposition_count),
      reviewDispositionPendingCount: numberOrZero(operational.review_disposition_pending_count),
    },
    pendingControls: arrayOfObjects(report.pending_controls),
    unresolvedControls: arrayOfObjects(report.unresolved_controls),
    pendingReviewDispositions: arrayOfObjects(report.pending_review_dispositions),
    latestAgentRuns: arrayOfObjects(report.agent_runs).slice(-5),
    branchEvents: arrayOfObjects(report.branch_events),
    allowedDecisionActions: arrayOfStrings(report.allowed_decision_actions),
  };
}

function buildContextSummary(report, options = {}) {
  const details = buildContextDetails(report);
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 5;
  const op = details.operationalSummary;
  const lines = [
    "TS workspace context:",
    `- workspace: ${details.workspaceRoot || "(unknown)"}; compute_workspace_id: ${details.workspaceId || "(missing)"}`,
    `- report: ${details.reportId || "(none)"}; revision: ${details.workspaceRevision || "(none)"}; valid: ${details.valid}`,
    `- operational_revision: ${details.operationalRevision || "(none)"}; calculations=${op.calculationFileCount}; agent_runs=${op.agentRunCount}; failed=${op.agentRunFailedCount}; pending=${op.agentRunPendingCount}; pending_review_responses=${op.reviewDispositionPendingCount}; unresolved_controls=${op.controlUnresolvedCount}; ambiguous_submissions=${op.ambiguousSubmissionCount}`,
    `- current_node: ${details.currentNode || "(none)"}; open_nodes: ${details.openNodes.length ? details.openNodes.map(formatNode).join("; ") : "(none)"}`,
    `- focus_claims: ${details.focusClaims.length ? details.focusClaims.map(formatClaim).join("; ") : "(none)"}`,
    `- accepted_refs: ${formatList(details.acceptedRefs, maxItems)}`,
    `- counts: closed_nodes=${details.closedNodeCount}; claims=${details.claimCount}; evidence=${details.evidenceCount}; gate_results=${details.gateResultCount}`,
    `- claim_status: ${formatCounts(details.claimStatusCounts)}`,
    `- gate_verdicts: ${formatCounts(details.gateVerdictCounts)}`,
  ];
  if (details.pendingControls.length) {
    lines.push(`- pending_controls: ${details.pendingControls.map(formatControl).join(", ")}`);
  }
  if (details.unresolvedControls.length) {
    lines.push(`- unresolved_controls: ${details.unresolvedControls.map(formatControl).join(", ")}`);
  }
  if (details.pendingReviewDispositions.length) {
    lines.push(`- pending_review_dispositions: ${details.pendingReviewDispositions.map((item) => `${item.task_id || "?"}:${item.operation || "?"}`).join(", ")}`);
  }
  lines.push(`- branch_events: ${formatBranchList(details.branchEvents, maxItems)}`);
  lines.push(`- allowed_decision_actions: ${formatList(details.allowedDecisionActions, maxItems)}`);
  if (details.latestAgentRuns.length) {
    lines.push(`- latest_agent_runs: ${details.latestAgentRuns.map((run) => `${run.task_id || "?"}:${run.role || "?"}/${run.operation || "?"}/${run.status || "?"}`).join(", ")}`);
  }
  if (details.validationFindings.length) {
    lines.push(`- validation_findings: ${details.validationFindings.slice(0, maxItems).map((item) => `${item.code || "finding"}:${item.message || ""}`).join("; ")}`);
  }
  lines.push("- authority: the Root Agent selects research actions and parent nodes; tags are display metadata only.");
  lines.push("- contract: use ts_workspace_context/ts_workspace_decision_draft/ts_workspace_decision_validate/ts_workspace_decision_apply; do not edit canonical state files by hand.");
  return lines.join("\n");
}

function buildNodeContextSummary(context, options = {}) {
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 8;
  const node = objectOrEmpty(context.node);
  const result = objectOrEmpty(node.result);
  const artifacts = objectOrEmpty(context.artifact_paths || node.artifacts);
  return [
    "TS historical node context:",
    `- node: ${node.node_id || "?"}; state=${node.state || "?"}; tags=${formatList(arrayOfStrings(node.tags), maxItems)}`,
    `- parent: ${node.parent_node || "(none)"}; lineage: ${formatList(arrayOfStrings(context.lineage), maxItems)}`,
    `- objective: ${node.objective || "(none)"}`,
    `- outcome: ${result.outcome || "(none)"}; summary: ${result.summary || "(none)"}`,
    `- claim_refs: ${formatList(arrayOfStrings(node.claim_refs), maxItems)}`,
    `- operation_refs: ${formatList(arrayOfStrings(context.operation_refs || node.operation_refs), maxItems)}`,
    `- evidence: ${formatEvidenceList(arrayOfObjects(context.evidence), maxItems)}`,
    `- gate_results: ${arrayOfObjects(context.gate_results).slice(0, maxItems).map((item) => `${item.gate_result_id || "?"}/${item.gate || "?"}/${item.verdict || "?"}`).join("; ") || "(none)"}`,
    `- artifact_paths: ${formatArtifactPaths(artifacts)}`,
    `- agent_runs: ${arrayOfObjects(context.agent_runs).slice(-maxItems).map((item) => `${item.task_id || "?"}:${item.role || "?"}/${item.operation || "?"}/${item.status || "?"}`).join("; ") || "(none)"}`,
    "- contract: this report is read-only; node tags do not authorize or select later actions.",
  ].join("\n");
}

function buildLineageContextSummary(context, options = {}) {
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 8;
  const fromNode = objectOrEmpty(objectOrEmpty(context.from_node).node);
  const anchorNode = objectOrEmpty(objectOrEmpty(context.anchor_node).node);
  return [
    "TS lineage context:",
    `- trigger: ${formatNodeState(fromNode)}`,
    `- selected_checkpoint: ${formatNodeState(anchorNode)}`,
    `- attempted_since_checkpoint: ${arrayOfObjects(context.path_delta).slice(0, maxItems).map(formatNodeState).join("; ") || "(none)"}`,
    "- authority: the Root Agent decides whether and how to branch; the kernel only validates parent-node topology.",
  ].join("\n");
}

function parseJsonOutput(result) {
  if (result && typeof result === "object") {
    for (const key of ["stdout", "output", "text"]) {
      if (typeof result[key] === "string" && result[key].trim()) return JSON.parse(result[key]);
    }
  }
  if (typeof result === "string" && result.trim()) return JSON.parse(result);
  if (result && typeof result === "object" && typeof result.stderr === "string" && result.stderr.trim()) {
    const stderr = result.stderr.trim();
    try {
      const payload = JSON.parse(stderr);
      if (payload && typeof payload.error === "string" && payload.error.trim()) throw new Error(payload.error.trim());
    } catch (error) {
      if (error instanceof Error && error.message !== stderr) throw error;
    }
    throw new Error(stderr);
  }
  throw new Error("command result did not contain JSON stdout");
}

function toolText(text, details = {}) {
  return { content: [{ type: "text", text }], details };
}

function formatNode(node) {
  const tags = node.tags.length ? `[${node.tags.join(",")}]` : "";
  return `${node.nodeId || "node"}${tags}/${node.state || "state"}`;
}

function formatNodeState(node) {
  const tags = arrayOfStrings(node.tags);
  const result = objectOrEmpty(node.result);
  return `${node.node_id || "?"}${tags.length ? `[${tags.join(",")}]` : ""}/${node.state || "?"}/${result.outcome || "pending"}`;
}

function formatClaim(claim) {
  return `${claim.claimId || "claim"}/${claim.status || "?"}: ${claim.statement || ""}`;
}

function formatControl(item) {
  return `${item.operation || "?"}:${item.intent_id || "?"}:${item.error_class || item.state || "pending"}`;
}

function formatBranchList(values, maxItems) {
  if (!values.length) return "(none)";
  return values.slice(-maxItems).map((item) => `${item.parent_node || "root"}->${item.node_id || "?"}`).join(", ");
}

function formatEvidenceList(values, maxItems) {
  if (!values.length) return "(none)";
  return values.slice(0, maxItems).map((item) => `${item.evidence_id || "?"}/${item.kind || "evidence"}/${item.state || "?"}: ${item.summary || ""}`).join("; ");
}

function formatArtifactPaths(value) {
  return ["inputs", "outputs", "attempts", "remote", "scratch"]
    .filter((key) => typeof value[key] === "string" && value[key].trim())
    .map((key) => `${key}=${value[key]}`)
    .join(", ") || "(none)";
}

function formatCounts(value) {
  const entries = Object.entries(value).sort(([left], [right]) => left.localeCompare(right));
  return entries.length ? entries.map(([key, count]) => `${key}=${count}`).join(", ") : "(none)";
}

function formatList(values, maxItems) {
  if (!values.length) return "(none)";
  const visible = values.slice(0, maxItems);
  return visible.join(", ") + (values.length > visible.length ? ` (+${values.length - visible.length} more)` : "");
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
  process.stdout.write(JSON.stringify({ summary: buildContextSummary(report), details: buildContextDetails(report) }, null, 2) + "\n");
  return 0;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {
  buildLineageContextSummary,
  buildContextDetails,
  buildContextSummary,
  buildNodeContextSummary,
  findWorkspaceRoot,
  isWorkspaceRoot,
  parseJsonOutput,
  resolveWorkspaceRoot,
  toolText,
};
