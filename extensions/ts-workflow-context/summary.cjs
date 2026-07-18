"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = [
  "manifest.json",
  "tree.json",
  "evidence_registry.json",
  "mechanism_model.json",
  "pathway_model.json",
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

  return {
    reportId: report.report_id || "",
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
      phase: node.phase || "",
      lifecycle: node.lifecycle || "",
      hypothesis: node.hypothesis || "",
    })),
    closedNodeCount: numberOrZero(report.closed_node_count),
    evidenceCount: numberOrZero(report.evidence_count),
    hypothesisSummary: activeHypothesis.summary || "",
    openPredictions: arrayOfObjects(hypothesisContext.open_predictions).map((prediction) => ({
      predictionId: prediction.prediction_id || "",
      phase: prediction.phase || "",
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
    allowedDecisionActions: arrayOfStrings(report.allowed_decision_actions),
  };
}

function buildContextSummary(report, options = {}) {
  const details = buildContextDetails(report);
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 5;
  const lines = [
    "TS workspace context:",
    `- workspace: ${details.workspaceRoot || "(unknown)"}`,
    `- report: ${details.reportId || "(none)"}; valid: ${details.valid}`,
    `- current_node: ${details.currentNode || "(none)"}; focus_hypothesis: ${details.focusHypothesisId || "(none)"}`,
    `- focus_pathway: ${details.focusPathwayId || "(none)"}; accepted_ts_refs: ${formatList(details.acceptedTsRefs, maxItems)}`,
    `- open_nodes: ${details.openNodes.length ? details.openNodes.map(formatNode).join("; ") : "(none)"}`,
    `- counts: closed_nodes=${details.closedNodeCount}; evidence=${details.evidenceCount}`,
  ];

  if (details.hypothesisSummary) {
    lines.push(`- active_hypothesis: ${details.hypothesisSummary}`);
  }
  lines.push(`- open_predictions: ${formatPredictionList(details.openPredictions, maxItems)}`);
  lines.push(`- supported_predictions: ${formatList(details.supportedPredictions, maxItems)}`);
  lines.push(`- refuted_predictions: ${formatList(details.refutedPredictions, maxItems)}`);
  lines.push(`- required_next_evidence: ${formatList(details.requiredNextEvidence, maxItems)}`);
  lines.push(`- branch_events: ${formatBranchList(details.branchEvents, maxItems)}`);
  lines.push(`- allowed_decision_actions: ${formatList(details.allowedDecisionActions, maxItems)}`);

  if (details.validationFindings.length) {
    lines.push(
      `- validation_findings: ${details.validationFindings
        .slice(0, maxItems)
        .map((finding) => `${finding.code || "finding"}:${finding.message || finding.path || ""}`)
        .join("; ")}`
    );
  }

  lines.push(
    "- contract: use ts_workspace_context/ts_workspace_validate/ts_workspace_decision; do not edit workspace state files by hand; shell fallbacks must use an explicit TSAgentSkill root, not cwd-relative scripts."
  );
  lines.push("- contract: every post-n000 mechanism node must carry payload.hypothesis_ref.");
  return lines.join("\n");
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
  throw new Error("command result did not contain JSON stdout");
}

function toolText(text, details = {}) {
  return { content: [{ type: "text", text }], details };
}

function formatNode(node) {
  return `${node.nodeId || "node"}:${node.phase || "phase"}/${node.lifecycle || "state"}`;
}

function formatPredictionList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  return values
    .slice(0, maxItems)
    .map((item) => `${item.predictionId || "prediction"}:${item.phase || "phase"}`)
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

function formatList(values, maxItems) {
  if (!values.length) {
    return "(none)";
  }
  const visible = values.slice(0, maxItems);
  const suffix = values.length > visible.length ? ` (+${values.length - visible.length} more)` : "";
  return visible.join(", ") + suffix;
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
  buildContextDetails,
  buildContextSummary,
  findWorkspaceRoot,
  isWorkspaceRoot,
  parseJsonOutput,
  resolveWorkspaceRoot,
  toolText,
};
