"use strict";

const { createHash } = require("node:crypto");
const { existsSync, lstatSync, readFileSync, readdirSync, realpathSync, statSync } = require("node:fs");
const { extname, isAbsolute, relative, resolve, sep } = require("node:path");

const RENDER_OPERATIONS = Object.freeze(["render", "compare", "animate", "mechanism"]);
const RENDER_EXTENSIONS = Object.freeze({
  render: new Set([".png", ".jpg", ".jpeg"]),
  compare: new Set([".png", ".jpg", ".jpeg"]),
  animate: new Set([".gif"]),
  mechanism: new Set([".png", ".jpg", ".jpeg"]),
});
const REPORT_MANIFEST_SCHEMA = "ts-report-package/1";
const REPORT_MANIFEST_MAX_BYTES = 2 * 1024 * 1024;
const REPORT_MANIFEST_MAX_FILES = 512;
const REQUIRED_REPORT_FILES = Object.freeze([
  "final_report.md",
  "report_context.json",
  "email_summary.md",
]);

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

function validateCreatedRenderOutput(root, outputRef) {
  const workspaceRoot = requireWorkspaceRoot(root);
  const ref = normalizeRef(outputRef);
  requirePrefix(ref, ["nodes/"]);
  const path = resolve(workspaceRoot, ref);
  assertWithin(workspaceRoot, path);
  assertNoSymlinkComponents(workspaceRoot, ref);
  if (!existsSync(path) || !statSync(path).isFile() || statSync(path).size < 1) {
    throw new Error("render backend reported success but the bound output is missing or empty");
  }
  return ref;
}

function validateCreatedReportPackage(root, packageRef, manifestDigest, workspaceRevision) {
  const workspaceRoot = requireWorkspaceRoot(root);
  const ref = normalizeRef(packageRef);
  requirePrefix(ref, ["reports/"]);
  const packagePath = resolve(workspaceRoot, ref);
  assertWithin(workspaceRoot, packagePath);
  assertNoSymlinkComponents(workspaceRoot, ref);
  if (!existsSync(packagePath) || !statSync(packagePath).isDirectory()) {
    throw new Error("report builder reported success but the bound package directory is missing");
  }

  const manifestRef = `${ref}/package_manifest.json`;
  const manifestPath = resolve(workspaceRoot, manifestRef);
  assertNoSymlinkComponents(workspaceRoot, manifestRef);
  if (!existsSync(manifestPath) || !statSync(manifestPath).isFile()) {
    throw new Error("report package manifest is missing");
  }
  const manifestStat = statSync(manifestPath);
  if (manifestStat.size < 1 || manifestStat.size > REPORT_MANIFEST_MAX_BYTES) {
    throw new Error("report package manifest has an invalid size");
  }
  const manifestBytes = readFileSync(manifestPath);
  const actualManifestDigest = sha256Bytes(manifestBytes);
  if (actualManifestDigest !== requireDigest(manifestDigest, "manifest digest")) {
    throw new Error("report package manifest digest does not match the generated file");
  }

  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8"));
  } catch (error) {
    throw new Error(`report package manifest is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!isPlainObject(manifest)) throw new Error("report package manifest must be an object");
  rejectUnknownKeys(manifest, ["schema_version", "workspace_revision", "files"], "report package manifest");
  if (manifest.schema_version !== REPORT_MANIFEST_SCHEMA) {
    throw new Error(`report package manifest schema_version must be ${REPORT_MANIFEST_SCHEMA}`);
  }
  const expectedRevision = requireDigest(workspaceRevision, "workspace revision");
  if (manifest.workspace_revision !== expectedRevision) {
    throw new Error("report package workspace revision does not match the builder result");
  }
  if (!Array.isArray(manifest.files) || manifest.files.length > REPORT_MANIFEST_MAX_FILES) {
    throw new Error(`report package manifest files must be an array with at most ${REPORT_MANIFEST_MAX_FILES} entries`);
  }

  const listedRefs = new Set();
  for (const [index, entry] of manifest.files.entries()) {
    if (!isPlainObject(entry)) throw new Error(`report package manifest files[${index}] must be an object`);
    rejectUnknownKeys(entry, ["ref", "sha256", "size_bytes"], `report package manifest files[${index}]`);
    const fileRef = normalizeRef(entry.ref);
    if (fileRef === "package_manifest.json") {
      throw new Error("report package manifest must not list itself");
    }
    if (listedRefs.has(fileRef)) throw new Error(`report package manifest contains duplicate ref: ${fileRef}`);
    listedRefs.add(fileRef);
    const expectedDigest = requireDigest(entry.sha256, `manifest files[${index}].sha256`);
    if (!Number.isSafeInteger(entry.size_bytes) || entry.size_bytes < 0) {
      throw new Error(`manifest files[${index}].size_bytes must be a non-negative safe integer`);
    }
    const workspaceFileRef = `${ref}/${fileRef}`;
    const filePath = resolve(workspaceRoot, workspaceFileRef);
    assertWithin(packagePath, filePath);
    assertNoSymlinkComponents(workspaceRoot, workspaceFileRef);
    if (!existsSync(filePath) || !statSync(filePath).isFile()) {
      throw new Error(`report package file is missing or not regular: ${fileRef}`);
    }
    const fileBytes = readFileSync(filePath);
    if (fileBytes.length !== entry.size_bytes) {
      throw new Error(`report package file size does not match the manifest: ${fileRef}`);
    }
    if (sha256Bytes(fileBytes) !== expectedDigest) {
      throw new Error(`report package file digest does not match the manifest: ${fileRef}`);
    }
  }

  for (const requiredRef of REQUIRED_REPORT_FILES) {
    if (!listedRefs.has(requiredRef)) throw new Error(`report package manifest is missing required file: ${requiredRef}`);
    if (statSync(resolve(packagePath, requiredRef)).size < 1) {
      throw new Error(`report package required file is empty: ${requiredRef}`);
    }
  }
  const assetsPath = resolve(packagePath, "assets");
  if (!existsSync(assetsPath) || !statSync(assetsPath).isDirectory() || lstatSync(assetsPath).isSymbolicLink()) {
    throw new Error("report package assets directory is missing or invalid");
  }

  const actualRefs = collectRegularFileRefs(packagePath);
  actualRefs.delete("package_manifest.json");
  if (actualRefs.size !== listedRefs.size || [...actualRefs].some((item) => !listedRefs.has(item))) {
    throw new Error("report package contents do not match the manifest file list");
  }
  return {
    package_ref: ref,
    manifest_ref: manifestRef,
    manifest_digest: actualManifestDigest,
    workspace_revision: expectedRevision,
    file_count: listedRefs.size,
  };
}

function collectRegularFileRefs(root) {
  const refs = new Set();
  const visit = (directory, prefix) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const itemRef = prefix ? `${prefix}/${entry.name}` : entry.name;
      const itemPath = resolve(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`report package contains a symbolic link: ${itemRef}`);
      if (entry.isDirectory()) visit(itemPath, itemRef);
      else if (entry.isFile()) refs.add(itemRef);
      else throw new Error(`report package contains a non-regular entry: ${itemRef}`);
    }
  };
  visit(root, "");
  return refs;
}

function sha256Bytes(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function requireDigest(value, label) {
  const digest = requireString(value, label, 71);
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label} must be a sha256 digest`);
  return digest;
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
  validateCreatedRenderOutput,
  validateCreatedReportPackage,
  validateRenderRequest,
  validateReportRequest,
  validateTaskNodeScope,
};
