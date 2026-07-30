"use strict";

const fs = require("node:fs");
const path = require("node:path");

const {
  buildBranchContextSummary,
  buildContextSummary,
  buildNodeContextSummary,
} = require("../extensions/ts-workflow-context/summary.cjs");

const REVIEW_CEILINGS = Object.freeze({
  mechanism: ["mechanism"],
  candidate: ["mechanism", "candidate"],
  tsfreq: ["mechanism", "candidate", "tsfreq"],
  connectivity: ["mechanism", "candidate", "tsfreq", "connectivity"],
  final_audit: ["mechanism", "candidate", "tsfreq", "connectivity", "accepted_audit", "pathway_audit"],
  program_failure: ["program"],
});

const LIMITS = Object.freeze({
  maxQuestionChars: 4000,
  maxEvidenceRefs: 16,
  maxArtifactRefs: 4,
  maxArtifactBytes: 16 * 1024,
  maxArtifactTotalBytes: 64 * 1024,
  maxPacketBytes: 96 * 1024,
});

const TEXT_EXTENSIONS = new Set([
  ".com", ".csv", ".gjf", ".json", ".log", ".md", ".out", ".txt", ".xyz", ".yaml", ".yml", ".tsv",
]);

function validateSubagentRequest(request) {
  if (!isPlainObject(request)) throw new Error("subagent request must be an object");
  rejectUnknownKeys(request, [
    "reviewType", "question", "root", "nodeId", "fromNode", "anchorNode", "evidenceRefs", "artifactRefs",
  ], "subagent request");

  const reviewType = requireString(request.reviewType, "reviewType", 64);
  if (!Object.hasOwn(REVIEW_CEILINGS, reviewType)) {
    throw new Error(`unsupported reviewType: ${reviewType}`);
  }
  const question = requireString(request.question, "question", LIMITS.maxQuestionChars);
  const root = optionalString(request.root, "root", 4096);
  const nodeId = optionalString(request.nodeId, "nodeId", 128);
  const fromNode = optionalString(request.fromNode, "fromNode", 128);
  const anchorNode = optionalString(request.anchorNode, "anchorNode", 128);
  if (Boolean(fromNode) !== Boolean(anchorNode)) {
    throw new Error("fromNode and anchorNode must be provided together");
  }
  const evidenceRefs = stringArray(request.evidenceRefs, "evidenceRefs", LIMITS.maxEvidenceRefs, 256);
  const artifactRefs = stringArray(request.artifactRefs, "artifactRefs", LIMITS.maxArtifactRefs, 4096);

  return { reviewType, question, root, nodeId, fromNode, anchorNode, evidenceRefs, artifactRefs };
}

function buildTaskPacket({ runId, workspaceRoot, request, workspaceReport, nodeContext, branchContext }) {
  const normalized = validateSubagentRequest(request);
  const root = path.resolve(requireString(workspaceRoot, "workspaceRoot", 4096));
  if (!isPlainObject(workspaceReport)) throw new Error("workspaceReport must be an object");
  if (workspaceReport.workspace_root && path.resolve(String(workspaceReport.workspace_root)) !== root) {
    throw new Error("workspace report root does not match requested workspace");
  }

  validateSelectedContexts(normalized, nodeContext, branchContext);
  const contexts = uniqueNodeContexts(nodeContext, branchContext);
  const evidenceMap = collectEvidence(contexts);
  const selectedEvidenceIds = normalized.evidenceRefs.length
    ? normalized.evidenceRefs
    : Array.from(evidenceMap.keys()).slice(0, LIMITS.maxEvidenceRefs);
  for (const evidenceId of selectedEvidenceIds) {
    if (!evidenceMap.has(evidenceId)) throw new Error(`evidence ref is outside selected context: ${evidenceId}`);
  }

  const artifactPolicy = collectArtifactPolicy(contexts);
  const artifactExcerpts = normalized.artifactRefs.map((ref) => readArtifactExcerpt(root, ref, artifactPolicy));
  const totalArtifactBytes = artifactExcerpts.reduce((total, item) => total + Buffer.byteLength(item.text, "utf8"), 0);
  if (totalArtifactBytes > LIMITS.maxArtifactTotalBytes) {
    throw new Error(`artifact excerpts exceed ${LIMITS.maxArtifactTotalBytes} bytes`);
  }

  const nodeIds = collectNodeIds(nodeContext, branchContext);
  const focus = isPlainObject(workspaceReport.focus) ? workspaceReport.focus : {};
  const packet = {
    schema_version: "ts-subagent-task/1",
    run_id: requireString(runId, "runId", 128),
    authority: "advisory",
    review_type: normalized.reviewType,
    evidence_ceiling: [...REVIEW_CEILINGS[normalized.reviewType]],
    question: normalized.question,
    workspace_root: root,
    scope: {
      report_id: typeof workspaceReport.report_id === "string" ? workspaceReport.report_id : "",
      node_ids: nodeIds,
      hypothesis_id: stringOrNull(focus.focus_hypothesis_id),
      pathway_id: stringOrNull(focus.focus_pathway_id),
    },
    context: {
      workspace: buildContextSummary(workspaceReport),
      node: nodeContext ? buildNodeContextSummary(nodeContext) : null,
      backtrack: branchContext ? buildBranchContextSummary(branchContext) : null,
    },
    evidence: selectedEvidenceIds.map((id) => evidenceMap.get(id)),
    artifact_excerpts: artifactExcerpts,
    basis_allowlist: [...selectedEvidenceIds, ...artifactExcerpts.map((item) => item.ref)],
    output_contract: {
      schema_version: "ts-subagent-advice/1",
      authority: "advisory",
      json_only: true,
      evidence_ceiling: [...REVIEW_CEILINGS[normalized.reviewType]],
    },
  };

  const packetBytes = Buffer.byteLength(JSON.stringify(packet), "utf8");
  if (packetBytes > LIMITS.maxPacketBytes) throw new Error(`task packet exceeds ${LIMITS.maxPacketBytes} bytes`);
  return packet;
}

function validateSelectedContexts(request, nodeContext, branchContext) {
  if (request.nodeId) {
    const actual = nodeContext && nodeContext.node && nodeContext.node.node_id;
    if (actual !== request.nodeId) throw new Error(`node context does not match nodeId: ${request.nodeId}`);
  } else if (nodeContext) {
    throw new Error("nodeContext was provided without nodeId");
  }
  if (request.fromNode) {
    const fromId = branchContext && branchContext.from_node && branchContext.from_node.node
      && branchContext.from_node.node.node_id;
    const anchorId = branchContext && branchContext.anchor_node && branchContext.anchor_node.node
      && branchContext.anchor_node.node.node_id;
    if (fromId !== request.fromNode || anchorId !== request.anchorNode) {
      throw new Error("branch context does not match fromNode/anchorNode");
    }
  } else if (branchContext) {
    throw new Error("branchContext was provided without fromNode/anchorNode");
  }
}

function uniqueNodeContexts(nodeContext, branchContext) {
  const values = [];
  if (nodeContext) values.push(nodeContext);
  if (branchContext && branchContext.from_node) values.push(branchContext.from_node);
  if (branchContext && branchContext.anchor_node) values.push(branchContext.anchor_node);
  const seen = new Set();
  return values.filter((value) => {
    const nodeId = value && value.node && value.node.node_id;
    if (!nodeId || seen.has(nodeId)) return false;
    seen.add(nodeId);
    return true;
  });
}

function collectEvidence(contexts) {
  const evidence = new Map();
  for (const context of contexts) {
    for (const item of Array.isArray(context.evidence) ? context.evidence : []) {
      if (!isPlainObject(item) || typeof item.evidence_id !== "string" || !item.evidence_id.trim()) continue;
      evidence.set(item.evidence_id, {
        evidence_id: item.evidence_id,
        node_id: stringOrNull(item.node_id),
        kind: stringOrNull(item.kind),
        role: stringOrNull(item.role),
        evidence_tier: stringOrNull(item.evidence_tier),
        summary: typeof item.summary === "string" ? item.summary : "",
        quality: isPlainObject(item.quality) ? item.quality : {},
        path: typeof item.path === "string" ? item.path : null,
      });
    }
  }
  return evidence;
}

function collectArtifactPolicy(contexts) {
  const directories = new Set();
  const exactPaths = new Set();
  for (const context of contexts) {
    const refs = isPlainObject(context.artifact_refs) ? context.artifact_refs : {};
    const nodeArtifacts = isPlainObject(refs.node_artifacts) ? refs.node_artifacts : {};
    for (const value of Object.values(nodeArtifacts)) {
      if (typeof value === "string" && value.trim()) directories.add(normalizeRelativeRef(value));
    }
    for (const key of ["evidence_paths", "source_files"]) {
      for (const value of Array.isArray(refs[key]) ? refs[key] : []) {
        if (typeof value === "string" && value.trim()) exactPaths.add(normalizeRelativeRef(value));
      }
    }
  }
  return { directories: [...directories], exactPaths: [...exactPaths] };
}

function readArtifactExcerpt(root, inputRef, policy) {
  const ref = normalizeRelativeRef(inputRef);
  const allowed = policy.exactPaths.includes(ref)
    || policy.directories.some((directory) => ref === directory || ref.startsWith(`${directory}/`));
  if (!allowed) throw new Error(`artifact ref is outside selected node context: ${ref}`);
  const extension = path.extname(ref).toLowerCase();
  if (!TEXT_EXTENSIONS.has(extension)) throw new Error(`artifact is not an allowlisted text type: ${ref}`);

  const absolute = path.resolve(root, ref);
  assertInside(root, absolute, `artifact path escapes workspace: ${ref}`);
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) throw new Error(`artifact file does not exist: ${ref}`);
  const realRoot = fs.realpathSync(root);
  const realArtifact = fs.realpathSync(absolute);
  assertInside(realRoot, realArtifact, `artifact symlink escapes workspace: ${ref}`);

  const stat = fs.statSync(realArtifact);
  const tail = extension === ".log" || extension === ".out";
  const length = Math.min(stat.size, LIMITS.maxArtifactBytes);
  const start = tail ? Math.max(0, stat.size - length) : 0;
  const buffer = Buffer.alloc(length);
  const handle = fs.openSync(realArtifact, "r");
  try {
    fs.readSync(handle, buffer, 0, length, start);
  } finally {
    fs.closeSync(handle);
  }
  if (buffer.includes(0)) throw new Error(`artifact contains binary data: ${ref}`);
  return {
    ref,
    selection: tail ? "tail" : "head",
    truncated: stat.size > length,
    original_bytes: stat.size,
    text: buffer.toString("utf8"),
  };
}

function collectNodeIds(nodeContext, branchContext) {
  const ids = [];
  const add = (value) => {
    if (typeof value === "string" && value && !ids.includes(value)) ids.push(value);
  };
  if (nodeContext && nodeContext.node) add(nodeContext.node.node_id);
  if (branchContext && branchContext.anchor_node && branchContext.anchor_node.node) {
    add(branchContext.anchor_node.node.node_id);
  }
  if (branchContext && Array.isArray(branchContext.path_delta)) {
    for (const node of branchContext.path_delta) add(node && node.node_id);
  }
  if (branchContext && branchContext.from_node && branchContext.from_node.node) add(branchContext.from_node.node.node_id);
  return ids;
}

function normalizeRelativeRef(value) {
  const text = requireString(value, "artifact ref", 4096).replace(/^@+/, "").replaceAll("\\", "/");
  if (path.posix.isAbsolute(text)) throw new Error(`artifact ref must be workspace-relative: ${text}`);
  const normalized = path.posix.normalize(text);
  if (normalized === ".." || normalized.startsWith("../") || normalized === ".") {
    throw new Error(`invalid artifact ref: ${text}`);
  }
  return normalized.replace(/^\.\//, "");
}

function assertInside(root, candidate, message) {
  const relative = path.relative(root, candidate);
  if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(message);
}

function rejectUnknownKeys(value, allowed, label) {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function optionalString(value, label, maxLength) {
  if (value === undefined || value === null || value === "") return null;
  return requireString(value, label, maxLength);
}

function stringArray(value, label, maxItems, maxLength) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  const result = value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringOrNull(value) {
  return typeof value === "string" && value.trim() ? value : null;
}

module.exports = {
  LIMITS,
  REVIEW_CEILINGS,
  buildTaskPacket,
  normalizeRelativeRef,
  validateSubagentRequest,
};
