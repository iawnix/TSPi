"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = [
  "workspace.json",
  "research_state.json",
  "phases.json",
  "claims.json",
  "claim_relations.json",
  "research_nodes.json",
  "observations.json",
  "proof_specs.json",
  "validation_results.json",
  "findings.json",
];

function normalizePath(value, cwd = process.cwd()) {
  if (typeof value !== "string" || !value.trim()) return null;
  return path.resolve(cwd, value.trim().replace(/^@+/, ""));
}

function isWorkspaceRoot(root) {
  if (!root || !WORKSPACE_MARKERS.every((name) => fs.existsSync(path.join(root, name)))) return false;
  try {
    const workspace = JSON.parse(fs.readFileSync(path.join(root, "workspace.json"), "utf8"));
    return workspace.schema_version === "ts-workspace/6" && workspace.kernel_protocol === "ts-research-kernel/6";
  } catch (_error) {
    return false;
  }
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
  const explicit = normalizePath(inputRoot || "", cwd);
  if (explicit) return isWorkspaceRoot(explicit) ? explicit : null;
  return findWorkspaceRoot(cwd, env);
}

function buildContextDetails(context) {
  const focus = objectOrEmpty(context.focus);
  const acceptance = objectOrEmpty(context.acceptance_summary);
  const operational = objectOrEmpty(context.operational_summary);
  return {
    projectionId: stringValue(context.projection_id),
    reportId: stringValue(context.report_id),
    workspaceId: stringValue(context.workspace_id),
    workspaceRevision: stringValue(context.workspace_revision),
    operationalRevision: stringValue(context.operational_revision),
    mode: stringValue(context.mode) || "frontier",
    valid: context.valid === true,
    validationFindings: arrayOfObjects(context.validation_findings),
    focusClaimRefs: arrayOfStrings(focus.claim_refs),
    focusNodeRefs: arrayOfStrings(focus.node_refs),
    acceptanceRecordRefs: arrayOfStrings(acceptance.record_refs),
    currentAcceptanceRefs: arrayOfStrings(acceptance.current_refs),
    staleAcceptanceRefs: arrayOfStrings(acceptance.stale_refs),
    workspaceBrief: objectOrEmpty(context.workspace_brief),
    researchPhases: arrayOfObjects(context.research_phases),
    claims: arrayOfObjects(context.claims),
    claimRelations: arrayOfObjects(context.claim_relations),
    researchNodes: arrayOfObjects(context.research_nodes),
    observations: arrayOfObjects(context.observations),
    validationSpecs: arrayOfObjects(context.proof_specs),
    validationResults: arrayOfObjects(context.validation_results),
    findings: arrayOfObjects(context.findings),
    acceptances: arrayOfObjects(context.acceptances),
    openFindings: arrayOfObjects(context.open_findings),
    incompleteValidation: arrayOfObjects(context.incomplete_validation),
    pendingReviewDispositions: arrayOfObjects(context.pending_review_dispositions),
    unresolvedControls: arrayOfObjects(context.unresolved_controls),
    recentDecisions: arrayOfObjects(context.recent_decisions),
    omitted: objectOrEmpty(context.omitted),
    retrieval: objectOrEmpty(context.retrieval),
    operationalSummary: {
      calculationFileCount: numberOrZero(operational.calculation_file_count),
      activityCount: numberOrZero(operational.activity_count),
      activityFailedCount: numberOrZero(operational.activity_failed_count),
      activityRunningCount: numberOrZero(operational.activity_running_count),
      agentRunCount: numberOrZero(operational.agent_run_count),
      agentRunFailedCount: numberOrZero(operational.agent_run_failed_count),
      agentRunPendingCount: numberOrZero(operational.agent_run_pending_count),
      reviewDispositionPendingCount: numberOrZero(operational.review_disposition_pending_count),
      controlUnresolvedCount: numberOrZero(operational.control_unresolved_count),
      ambiguousSubmissionCount: numberOrZero(operational.ambiguous_submission_count),
    },
  };
}

function buildContextSummary(context, options = {}) {
  if (context && context.changed === false) {
    return `TS context unchanged at ${context.workspace_revision || "unknown revision"}; operational revision ${context.operational_revision || "unknown"}.`;
  }
  const details = buildContextDetails(context);
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 4;
  const op = details.operationalSummary;
  const brief = details.workspaceBrief;
  const phases = arrayOfObjects(brief.phases);
  const nodes = arrayOfObjects(brief.nodes);
  const claims = arrayOfObjects(brief.claims);
  const briefFindings = arrayOfObjects(brief.open_findings);
  const validationGaps = arrayOfObjects(brief.incomplete_validation);
  const openNodes = nodes.filter((node) => node.status === "open");
  const lines = [
    "TS research context:",
    `- context: mode=${details.mode}; valid=${details.valid}`,
    `- delta_tokens: scientific_revision=${details.workspaceRevision || "(none)"}; operational_revision=${details.operationalRevision || "(none)"}`,
    `- focus: claims=${formatList(details.focusClaimRefs, maxItems)}; nodes=${formatList(details.focusNodeRefs, maxItems)}`,
    `- acceptance: current=${formatList(details.currentAcceptanceRefs, maxItems)}; history=${details.acceptanceRecordRefs.length}; stale=${details.staleAcceptanceRefs.length}`,
    `- phases: ${phases.length ? phases.slice(0, maxItems).map(formatPhase).join("; ") : "(none)"}`,
    `- trajectory: ${formatTrajectory(nodes, maxItems)}`,
    `- open_nodes: ${openNodes.length ? openNodes.slice(0, maxItems).map(formatNode).join("; ") : "(none)"}`,
    `- claims: ${claims.length ? claims.slice(0, maxItems).map(formatClaim).join("; ") : "(none)"}`,
    `- graph: relations=${details.claimRelations.length}; observations=${details.observations.length}; specs=${details.validationSpecs.length}; results=${details.validationResults.length}; findings=${details.findings.length}`,
    `- operations: calculations=${op.calculationFileCount}; activities=${op.activityCount}; activity_failures=${op.activityFailedCount}; agent_runs=${op.agentRunCount}; agent_failures=${op.agentRunFailedCount}; agent_pending=${op.agentRunPendingCount}; pending_review_responses=${op.reviewDispositionPendingCount}; unresolved_controls=${op.controlUnresolvedCount}; ambiguous_submissions=${op.ambiguousSubmissionCount}`,
  ];
  if (validationGaps.length) {
    lines.push(`- incomplete_validation: ${validationGaps.slice(0, maxItems).map(formatValidationGap).join("; ")}`);
  }
  if (briefFindings.length) {
    lines.push(`- open_findings: ${briefFindings.slice(0, maxItems).map(formatFinding).join("; ")}`);
  }
  if (details.unresolvedControls.length) {
    lines.push(`- unresolved_controls: ${details.unresolvedControls.slice(0, maxItems).map(formatControl).join("; ")}`);
  }
  if (details.pendingReviewDispositions.length) {
    lines.push(`- pending_review_dispositions: ${details.pendingReviewDispositions.slice(0, maxItems).map((item) => `${item.task_id || "?"}/${formatList(arrayOfStrings(item.claim_refs), 3)}`).join("; ")}`);
  }
  if (details.validationFindings.length) {
    lines.push(`- workspace_findings: ${details.validationFindings.slice(0, maxItems).map((item) => `${item.code || "finding"}:${item.message || ""}`).join("; ")}`);
  }
  if (Object.values(details.omitted).some((value) => numberOrZero(value) > 0)) {
    lines.push(`- omitted: ${formatCounts(details.omitted)}; retrieve a claim, node, finding, validation, or bounded subgraph explicitly.`);
  }
  lines.push("- authority: the Root Agent chooses research strategy; Claims hold hypotheses and falsifiers; the kernel validates and atomically commits explicit operations.");
  lines.push("- contract: draft, validate, and apply one ts-research-decision/3; never edit canonical registries directly.");
  return lines.join("\n");
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
    let payload;
    try {
      payload = JSON.parse(stderr);
    } catch (_error) {}
    const message = structuredErrorMessage(payload);
    if (message) throw new Error(message);
    throw new Error(stderr);
  }
  throw new Error("command result did not contain JSON stdout");
}

function structuredErrorMessage(payload) {
  if (!payload || typeof payload !== "object") return "";
  if (typeof payload.error === "string" && payload.error.trim()) return payload.error.trim();
  if (payload.error && typeof payload.error === "object" && typeof payload.error.message === "string") {
    return payload.error.message.trim();
  }
  return "";
}

function toolText(text, details = {}) {
  return { content: [{ type: "text", text }], details };
}

function formatNode(node) {
  const rationale = truncateText(stringValue(node.decision_rationale), 120);
  const title = truncateText(stringValue(node.title), 100);
  const objective = truncateText(stringValue(node.objective), 180);
  const deliverable = truncateText(stringValue(node.deliverable), 180);
  const identity = `${node.node_id || "node"}@${node.phase_ref || "phase"}/${node.status || "?"}`;
  return `${identity}: ${title || "Untitled Node"}; question=${objective || "(not recorded)"}; deliverable=${deliverable || "(not recorded)"}${rationale ? ` [decision=${rationale}]` : ""}`;
}

function formatTrajectory(nodes, maxItems) {
  if (!nodes.length) return "(none)";
  const visible = nodes.slice(-maxItems);
  const prefix = nodes.length > visible.length ? `(+${nodes.length - visible.length} earlier) ` : "";
  return prefix + visible.map((node) => {
    const outcome = truncateText(stringValue(node.result_summary), 100);
    return `${node.node_id || "node"}/${node.status || "?"}: ${node.title || node.objective || ""}${outcome ? ` => ${outcome}` : ""}`;
  }).join(" -> ");
}

function formatPhase(phase) {
  return `${phase.phase_id || "phase"}:${phase.title || ""} (${phase.open_node_count || 0} open / ${phase.node_count || 0} total)`;
}

function formatClaim(claim) {
  return `${claim.claim_id || "claim"}/${claim.status || "?"}: ${claim.statement || ""}`;
}

function formatValidationGap(item) {
  return `${item.proof_id || item.proof_ref || "spec"}:${item.dimension || item.status || "unevaluated"}`;
}

function formatFinding(item) {
  return `${item.finding_id || "finding"}/${item.severity || "?"}: ${item.statement || item.summary || ""}`;
}

function formatControl(item) {
  return `${item.node_id || "?"}/${item.intent_id || "?"}/${item.operation || "?"}:${item.error_class || item.state || "unresolved"}`;
}

function formatCounts(value) {
  const entries = Object.entries(value).sort(([left], [right]) => left.localeCompare(right));
  return entries.length ? entries.map(([key, count]) => `${key}=${numberOrZero(count)}`).join(", ") : "(none)";
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

function stringValue(value) {
  return typeof value === "string" ? value : "";
}

function truncateText(value, maximum) {
  const normalized = String(value || "").replace(/\s+/g, " ").trim();
  return normalized.length <= maximum ? normalized : `${normalized.slice(0, maximum - 3).trimEnd()}...`;
}

function main(argv) {
  const contextFlag = argv.indexOf("--context");
  if (contextFlag < 0 || !argv[contextFlag + 1]) {
    console.error("usage: node summary.cjs --context <context.json>");
    return 2;
  }
  const context = JSON.parse(fs.readFileSync(argv[contextFlag + 1], "utf8"));
  process.stdout.write(JSON.stringify({ summary: buildContextSummary(context), details: buildContextDetails(context) }, null, 2) + "\n");
  return 0;
}

if (require.main === module) process.exitCode = main(process.argv.slice(2));

module.exports = {
  buildContextDetails,
  buildContextSummary,
  findWorkspaceRoot,
  isWorkspaceRoot,
  parseJsonOutput,
  resolveWorkspaceRoot,
  toolText,
};
