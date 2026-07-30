"use strict";

const { existsSync, lstatSync, realpathSync, statSync } = require("node:fs");
const { dirname, extname, isAbsolute, relative, resolve, sep } = require("node:path");

const RENDER_OPERATIONS = Object.freeze(["render", "compare", "animate", "mechanism"]);
const RENDER_EXTENSIONS = Object.freeze({
  render: new Set([".png", ".jpg", ".jpeg"]),
  compare: new Set([".png", ".jpg", ".jpeg"]),
  animate: new Set([".gif"]),
  mechanism: new Set([".png", ".jpg", ".jpeg"]),
});

function validateRenderRequest(root, value) {
  const workspaceRoot = requireWorkspaceRoot(root);
  if (!isPlainObject(value)) throw new Error("render request must be an object");
  rejectUnknownKeys(value, ["operation", "nodeId", "inputRefs", "outputRef"], "render request");
  const operation = requireEnum(value.operation, "operation", RENDER_OPERATIONS);
  const nodeId = requireNodeId(value.nodeId);
  const inputRefs = uniqueStringArray(value.inputRefs, "inputRefs", 8, 4096);
  const expectedCounts = { render: [1, 1], compare: [2, 8], animate: [1, 1], mechanism: [2, 8] };
  const [minimum, maximum] = expectedCounts[operation];
  if (inputRefs.length < minimum || inputRefs.length > maximum) {
    throw new Error(`${operation} requires ${minimum === maximum ? minimum : `${minimum}-${maximum}`} inputRefs`);
  }
  const normalizedInputs = inputRefs.map((ref) => validateExistingRef(workspaceRoot, ref, ["inputs/", "nodes/"]));
  const outputRef = validateNewRef(workspaceRoot, value.outputRef, [`nodes/${nodeId}/outputs/`]);
  if (!RENDER_EXTENSIONS[operation].has(extname(outputRef).toLowerCase())) {
    throw new Error(`${operation} outputRef has an unsupported extension`);
  }
  const nodeRef = `nodes/${nodeId}/node.json`;
  validateExistingRef(workspaceRoot, nodeRef, [`nodes/${nodeId}/`]);
  return {
    operation,
    nodeId,
    inputRefs: normalizedInputs,
    outputRef,
    inputPaths: normalizedInputs.map((ref) => resolve(workspaceRoot, ref)),
    outputPath: resolve(workspaceRoot, outputRef),
  };
}

function validateReportRequest(root, value) {
  const workspaceRoot = requireWorkspaceRoot(root);
  if (!isPlainObject(value)) throw new Error("report request must be an object");
  rejectUnknownKeys(value, ["operation", "packageRef"], "report request");
  if (value.operation !== "build") throw new Error("report operation must be build");
  const packageRef = validateNewRef(workspaceRoot, value.packageRef, ["reports/"]);
  return {
    operation: "build",
    packageRef,
    packagePath: resolve(workspaceRoot, packageRef),
  };
}

function validateEmailRequest(root, value) {
  const workspaceRoot = requireWorkspaceRoot(root);
  if (!isPlainObject(value)) throw new Error("email request must be an object");
  rejectUnknownKeys(value, ["operation", "summaryRef", "draftRef", "recipients"], "email request");
  if (value.operation !== "draft") throw new Error("email operation must be draft; sending is unavailable");
  const summaryRef = validateExistingRef(workspaceRoot, value.summaryRef, ["reports/"]);
  if (!summaryRef.endsWith("/email_summary.md")) {
    throw new Error("email summaryRef must select a generated email_summary.md");
  }
  const contextRef = `${dirname(summaryRef).replaceAll("\\", "/")}/report_context.json`;
  validateExistingRef(workspaceRoot, contextRef, ["reports/"]);
  const draftRef = validateNewRef(workspaceRoot, value.draftRef, ["reports/"]);
  if (extname(draftRef).toLowerCase() !== ".json") throw new Error("email draftRef must end in .json");
  const recipients = uniqueStringArray(value.recipients, "recipients", 20, 320);
  if (!recipients.length) throw new Error("email draft requires at least one explicit recipient");
  for (const recipient of recipients) {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
      throw new Error(`invalid explicit email recipient: ${recipient}`);
    }
  }
  return {
    operation: "draft",
    summaryRef,
    summaryPath: resolve(workspaceRoot, summaryRef),
    contextRef,
    draftRef,
    draftPath: resolve(workspaceRoot, draftRef),
    recipients,
  };
}

function validateTaskNodeScope(workspaceReport, nodeIds) {
  if (!Array.isArray(nodeIds)) throw new Error("artifact task node_ids must be an array");
  if (!nodeIds.length) return [];
  if (!isPlainObject(workspaceReport) || !Array.isArray(workspaceReport.node_index)) {
    throw new Error("workspace report has no canonical node_index");
  }
  const knownNodeIds = new Set(
    workspaceReport.node_index
      .filter((item) => isPlainObject(item) && typeof item.node_id === "string")
      .map((item) => item.node_id),
  );
  for (const nodeId of nodeIds) {
    if (!knownNodeIds.has(nodeId)) {
      throw new Error(`artifact task node is absent from workspace report: ${nodeId}`);
    }
  }
  return [...nodeIds];
}

function requireWorkspaceRoot(root) {
  if (typeof root !== "string" || !root.trim() || !isAbsolute(root)) {
    throw new Error("workspace root must be an absolute path");
  }
  const resolved = realpathSync(root);
  if (!statSync(resolved).isDirectory()) throw new Error("workspace root must be a directory");
  return resolved;
}

function validateExistingRef(root, value, prefixes) {
  const ref = normalizeRef(value);
  requirePrefix(ref, prefixes);
  const path = resolve(root, ref);
  assertWithin(root, path);
  assertNoSymlinkComponents(root, ref);
  if (!existsSync(path) || !statSync(path).isFile()) throw new Error(`workspace input does not exist as a file: ${ref}`);
  return ref;
}

function validateNewRef(root, value, prefixes) {
  const ref = normalizeRef(value);
  requirePrefix(ref, prefixes);
  const path = resolve(root, ref);
  assertWithin(root, path);
  assertNoSymlinkComponents(root, ref);
  if (existsSync(path)) throw new Error(`artifact output already exists: ${ref}`);
  return ref;
}

function normalizeRef(value) {
  const ref = requireString(value, "workspace ref", 4096).replaceAll("\\", "/");
  if (isAbsolute(ref) || ref.startsWith("/") || /^[A-Za-z]:\//.test(ref)) {
    throw new Error("workspace ref must be relative");
  }
  const parts = ref.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error("workspace ref contains an empty, dot, or parent segment");
  }
  return parts.join("/");
}

function requirePrefix(ref, prefixes) {
  if (!prefixes.some((prefix) => ref.startsWith(prefix))) {
    throw new Error(`workspace ref is outside the allowed artifact roots: ${ref}`);
  }
}

function assertWithin(root, path) {
  const rel = relative(root, path);
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) {
    throw new Error("artifact path escapes the workspace root");
  }
}

function assertNoSymlinkComponents(root, ref) {
  let current = root;
  for (const part of ref.split("/")) {
    current = resolve(current, part);
    if (!existsSync(current)) return;
    if (lstatSync(current).isSymbolicLink()) {
      throw new Error(`workspace artifact path contains a symbolic link: ${ref}`);
    }
  }
}

function requireNodeId(value) {
  const nodeId = requireString(value, "nodeId", 128);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(nodeId)) throw new Error("nodeId contains unsafe characters");
  return nodeId;
}

function requireEnum(value, label, allowed) {
  if (!allowed.includes(value)) throw new Error(`invalid ${label}: ${value}`);
  return value;
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function uniqueStringArray(value, label, maxItems, maxLength) {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > maxItems) throw new Error(`${label} exceeds ${maxItems} items`);
  const result = value.map((item, index) => requireString(item, `${label}[${index}]`, maxLength));
  if (new Set(result).size !== result.length) throw new Error(`${label} contains duplicates`);
  return result;
}

function rejectUnknownKeys(value, allowed, label) {
  const allowedSet = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  RENDER_OPERATIONS,
  validateEmailRequest,
  validateRenderRequest,
  validateReportRequest,
  validateTaskNodeScope,
};
