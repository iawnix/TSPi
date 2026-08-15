"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = [
  "workspace.json",
  "research_state.json",
  "claims.json",
  "claim_relations.json",
  "research_acts.json",
  "observations.json",
  "validation_specs.json",
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
    return workspace.schema_version === "ts-workspace/4" && workspace.kernel_protocol === "ts-research-kernel/4";
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
    focusActRefs: arrayOfStrings(focus.act_refs),
    acceptanceRecordRefs: arrayOfStrings(acceptance.record_refs),
    currentAcceptanceRefs: arrayOfStrings(acceptance.current_refs),
    staleAcceptanceRefs: arrayOfStrings(acceptance.stale_refs),
    claims: arrayOfObjects(context.claims),
    claimRelations: arrayOfObjects(context.claim_relations),
    researchActs: arrayOfObjects(context.research_acts),
    observations: arrayOfObjects(context.observations),
    validationSpecs: arrayOfObjects(context.validation_specs),
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
      reviewRunCount: numberOrZero(operational.review_run_count),
      reviewRunFailedCount: numberOrZero(operational.review_run_failed_count),
      reviewRunPendingCount: numberOrZero(operational.review_run_pending_count),
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
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 6;
  const op = details.operationalSummary;
  const openActs = details.researchActs.filter((act) => act.status === "open");
  const lines = [
    "TS research context:",
    `- projection: ${details.projectionId || "(none)"}; mode=${details.mode}; valid=${details.valid}`,
    `- workspace: ${details.workspaceId || "(missing)"}; scientific_revision=${details.workspaceRevision || "(none)"}; operational_revision=${details.operationalRevision || "(none)"}`,
    `- focus: claims=${formatList(details.focusClaimRefs, maxItems)}; acts=${formatList(details.focusActRefs, maxItems)}`,
    `- acceptance: current=${formatList(details.currentAcceptanceRefs, maxItems)}; history=${details.acceptanceRecordRefs.length}; stale=${details.staleAcceptanceRefs.length}`,
    `- open_acts: ${openActs.length ? openActs.slice(0, maxItems).map(formatAct).join("; ") : "(none)"}`,
    `- claims: ${details.claims.length ? details.claims.slice(0, maxItems).map(formatClaim).join("; ") : "(none)"}`,
    `- graph: relations=${details.claimRelations.length}; observations=${details.observations.length}; specs=${details.validationSpecs.length}; results=${details.validationResults.length}; findings=${details.findings.length}`,
    `- operations: calculations=${op.calculationFileCount}; activities=${op.activityCount}; activity_failures=${op.activityFailedCount}; reviews=${op.reviewRunCount}; review_failures=${op.reviewRunFailedCount}; pending_review_responses=${op.reviewDispositionPendingCount}; unresolved_controls=${op.controlUnresolvedCount}; ambiguous_submissions=${op.ambiguousSubmissionCount}`,
  ];
  if (details.incompleteValidation.length) {
    lines.push(`- incomplete_validation: ${details.incompleteValidation.slice(0, maxItems).map(formatValidationGap).join("; ")}`);
  }
  if (details.openFindings.length) {
    lines.push(`- open_findings: ${details.openFindings.slice(0, maxItems).map(formatFinding).join("; ")}`);
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
    lines.push(`- omitted: ${formatCounts(details.omitted)}; retrieve a claim, act, finding, validation, or bounded subgraph explicitly.`);
  }
  lines.push("- authority: the Root Agent chooses hypotheses and research actions; the kernel validates and atomically commits explicit operations.");
  lines.push("- contract: draft, validate, and apply one ts-research-decision/1; never edit canonical registries directly.");
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

function formatAct(act) {
  return `${act.act_id || "act"}/${act.status || "?"}: ${act.objective || ""}`;
}

function formatClaim(claim) {
  return `${claim.claim_id || "claim"}/${claim.status || "?"}: ${claim.statement || ""}`;
}

function formatValidationGap(item) {
  return `${item.spec_id || item.spec_ref || "spec"}:${item.dimension || item.status || "unevaluated"}`;
}

function formatFinding(item) {
  return `${item.finding_id || "finding"}/${item.severity || "?"}: ${item.statement || item.summary || ""}`;
}

function formatControl(item) {
  return `${item.act_id || "?"}/${item.intent_id || "?"}/${item.operation || "?"}:${item.error_class || item.state || "unresolved"}`;
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
