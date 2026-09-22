"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WORKSPACE_MARKERS = ["workspace.json", "research_map.json", "transactions.jsonl"];

function isResearchMapRoot(root) {
  try {
    const map = JSON.parse(fs.readFileSync(path.join(root, "research_map.json"), "utf8"));
    return map.schema_version === "research-map/1" && typeof map.map_id === "string";
  } catch (_error) {
    return false;
  }
}

function normalizePath(value, cwd = process.cwd()) {
  if (typeof value !== "string" || !value.trim()) return null;
  return path.resolve(cwd, value.trim().replace(/^@+/, ""));
}

function isWorkspaceRoot(root) {
  if (!root || !WORKSPACE_MARKERS.every((name) => fs.existsSync(path.join(root, name)))) return false;
  if (!isResearchMapRoot(root)) return false;
  try {
    const workspace = JSON.parse(fs.readFileSync(path.join(root, "workspace.json"), "utf8"));
    return workspace.schema_version === "research-workspace/1" && workspace.kernel_protocol === "research-map/1";
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
  const source = objectOrEmpty(context);
  const map = objectOrEmpty(source.map || source.research_map || source);
  const progress = objectOrEmpty(map.progress || source.progress);
  return {
    map,
    mapId: stringValue(map.map_id),
    title: stringValue(map.title),
    revision: numberOrZero(map.revision),
    valid: source.valid !== false,
    phases: arrayOfObjects(map.phases),
    claims: arrayOfObjects(map.claims),
    nodes: arrayOfObjects(map.nodes),
    findings: arrayOfObjects(map.findings),
    gates: arrayOfObjects(map.gates),
    claimRelations: arrayOfObjects(map.claim_relations),
    focusClaimIds: arrayOfStrings(map.focus_claim_ids),
    focusNodeIds: arrayOfStrings(map.focus_node_ids),
    progress,
  };
}

function buildContextSummary(context, options = {}) {
  if (context && context.changed === false) {
    return `ResearchMap unchanged at revision ${context.revision ?? "unknown"}.`;
  }
  const details = buildContextDetails(context);
  const maxItems = Number.isInteger(options.maxItems) ? options.maxItems : 4;
  const phases = details.phases;
  const nodes = details.nodes;
  const claims = details.claims;
  const findings = details.findings;
  const openNodes = nodes.filter((node) => node.state !== "closed");
  const openFindings = findings.filter((finding) => finding.status === "open");
  const lines = [
    "ResearchMap context:",
    `- map: ${formatMapLabel(details)}; revision=${details.revision}; valid=${details.valid}`,
    `- focus: claims=${formatList(details.focusClaimIds, maxItems)}; nodes=${formatList(details.focusNodeIds, maxItems)}`,
    `- phases: ${phases.length ? phases.slice(0, maxItems).map(formatPhase).join("; ") : "(none)"}`,
    `- open_nodes: ${openNodes.length ? openNodes.slice(0, maxItems).map(formatNode).join("; ") : "(none)"}`,
    `- claims: ${claims.length ? claims.slice(0, maxItems).map(formatClaim).join("; ") : "(none)"}`,
    `- graph: relations=${details.claimRelations.length}; findings=${findings.length}; gates=${details.gates.length}`,
    `- progress: nodes=${numberOrZero(details.progress.node_count)}; closed=${numberOrZero(details.progress.closed_node_count)}; findings=${numberOrZero(details.progress.finding_count)}; gates=${numberOrZero(details.progress.gate_count)}`,
  ];
  if (openFindings.length) {
    lines.push(`- open_findings: ${openFindings.slice(0, maxItems).map(formatFinding).join("; ")}`);
  }
  lines.push("- authority: the Root Agent chooses research strategy; the ResearchKernel validates and atomically commits ChangeSets.");
  return lines.join("\n");
}

function formatMapLabel(details) {
  const title = truncateText(details.title, 100);
  const mapId = details.mapId;
  if (!title) return mapId && /^ws_[0-9a-f]{12,}$/i.test(mapId) ? "workspace" : (mapId || "(unknown)");
  // Canonical workspace IDs are useful in audit details, but a map summary is
  // a human-facing context line. Keep synthetic/non-workspace map IDs visible
  // for compatibility while letting a real workspace title carry the label.
  if (mapId && !/^ws_[0-9a-f]{12,}$/i.test(mapId)) return `${title} (${mapId})`;
  return title;
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
  const title = truncateText(stringValue(node.title), 100);
  const objective = truncateText(stringValue(node.objective), 180);
  return `${node.id || "node"}/${node.state || "?"}: ${title || "Untitled Node"}; objective=${objective || "(not recorded)"}`;
}

function formatPhase(phase) {
  return `${phase.id || "phase"}:${phase.title || ""}`;
}

function formatClaim(claim) {
  return `${claim.id || "claim"}/${claim.status || "?"}: ${claim.statement || ""}`;
}

function formatFinding(item) {
  return `${item.id || "finding"}/${item.kind || "?"}: ${item.statement || ""}`;
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
    console.error("usage: node tool-runtime.cjs --context <context.json>");
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
