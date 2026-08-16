"use strict";

const {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
} = require("node:fs");
const { createHash } = require("node:crypto");
const { isAbsolute, relative, resolve, sep } = require("node:path");

const RENDER_OPERATIONS = Object.freeze(["render", "compare", "animate", "mechanism"]);
const ACT_ID = /^act_[1-9][0-9]*$/;
const ARTIFACT_ID = /^art_[0-9a-f]{24}$/;
const OUTPUT_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function validateRenderRequest(rootValue, input, resolvedArtifacts) {
  const root = requireWorkspaceRoot(rootValue);
  if (!isPlainObject(input)) throw new Error("render request must be an object");
  rejectUnknownKeys(input, ["operation", "actId", "inputArtifactIds", "outputName"], "render request");
  const operation = requireEnum(input.operation, "render operation", RENDER_OPERATIONS);
  const actId = requireAct(root, input.actId);
  const inputArtifactIds = uniqueStrings(input.inputArtifactIds, "inputArtifactIds", 8, ARTIFACT_ID);
  const required = operation === "render" || operation === "animate" ? 1 : 2;
  if (inputArtifactIds.length < required || (required === 1 && inputArtifactIds.length !== 1)) {
    throw new Error(`${operation} requires ${required === 1 ? "exactly one" : "at least two"} input artifacts`);
  }
  if (!Array.isArray(resolvedArtifacts) || resolvedArtifacts.length !== inputArtifactIds.length) {
    throw new Error("render artifact resolution does not match the request");
  }
  const byId = new Map(resolvedArtifacts.map((item) => [item?.artifact_id, item]));
  const artifacts = inputArtifactIds.map((artifactId) => {
    const artifact = byId.get(artifactId);
    if (!isPlainObject(artifact) || artifact.artifact_id !== artifactId) {
      throw new Error(`render artifact was not resolved: ${artifactId}`);
    }
    const ref = requireString(artifact.path, "artifact path", 4096);
    const path = resolve(root, ...ref.split("/"));
    assertWithin(root, path);
    assertNoSymlinkComponents(root, ref);
    if (!existsSync(path) || !statSync(path).isFile()) throw new Error(`render input does not exist: ${artifactId}`);
    return { artifactId, ref, path, sha256: requireDigest(artifact.sha256, "artifact sha256") };
  });
  const outputName = requireString(input.outputName, "outputName", 128);
  if (!OUTPUT_NAME.test(outputName) || !/\.(?:gif|png)$/i.test(outputName)) {
    throw new Error("outputName must be a safe .png or .gif filename");
  }
  if (operation === "animate" && !/\.gif$/i.test(outputName)) throw new Error("animate outputName must end in .gif");
  if (operation !== "animate" && !/\.png$/i.test(outputName)) throw new Error(`${operation} outputName must end in .png`);
  const outputRef = `acts/${actId}/outputs/render/${outputName}`;
  const outputPath = resolve(root, ...outputRef.split("/"));
  assertWithin(root, outputPath);
  assertNoSymlinkComponents(root, outputRef);
  if (existsSync(outputPath)) throw new Error(`render output already exists: ${outputName}`);
  return { operation, actId, artifacts, outputName, outputRef, outputPath };
}

function validateReportRequest(rootValue, input) {
  const root = requireWorkspaceRoot(rootValue);
  if (!isPlainObject(input)) throw new Error("report request must be an object");
  rejectUnknownKeys(input, ["operation", "packageName"], "report request");
  if (input.operation !== "build") throw new Error("report operation must be build");
  const packageName = requireString(input.packageName, "packageName", 128);
  if (!OUTPUT_NAME.test(packageName)) throw new Error("packageName contains unsafe characters");
  const packageRef = `reports/${packageName}`;
  const packagePath = resolve(root, "reports", packageName);
  assertWithin(root, packagePath);
  assertNoSymlinkComponents(root, packageRef);
  if (existsSync(packagePath)) throw new Error(`report package already exists: ${packageName}`);
  return { operation: "build", packageName, packageRef, packagePath };
}

function validateCreatedRenderOutput(rootValue, outputRef) {
  const root = requireWorkspaceRoot(rootValue);
  const ref = requireString(outputRef, "render output ref", 4096);
  const path = resolve(root, ...ref.split("/"));
  assertWithin(root, path);
  assertNoSymlinkComponents(root, ref);
  if (!existsSync(path) || !statSync(path).isFile() || statSync(path).size < 1) {
    throw new Error("render backend did not create a non-empty regular output");
  }
  return { ref, size_bytes: statSync(path).size, sha256: sha256Bytes(readFileSync(path)) };
}

function validateCreatedReportPackage(rootValue, packageRef, expectedManifestDigest, expectedRevision, expectedOperationalRevision) {
  const root = requireWorkspaceRoot(rootValue);
  const ref = requireString(packageRef, "report package ref", 4096);
  const packagePath = resolve(root, ...ref.split("/"));
  assertWithin(root, packagePath);
  assertNoSymlinkComponents(root, ref);
  if (!existsSync(packagePath) || !statSync(packagePath).isDirectory()) throw new Error("report package is missing");
  const manifestPath = resolve(packagePath, "package_manifest.json");
  if (!existsSync(manifestPath) || !statSync(manifestPath).isFile()) throw new Error("report package manifest is missing");
  const manifestBytes = readFileSync(manifestPath);
  const manifestDigest = sha256Bytes(manifestBytes);
  if (manifestDigest !== requireDigest(expectedManifestDigest, "manifest digest")) {
    throw new Error("report package manifest digest mismatch");
  }
  const manifest = JSON.parse(manifestBytes.toString("utf8"));
  if (manifest.schema_version !== "ts-report-package/3") throw new Error("report package manifest schema is invalid");
  if (manifest.workspace_revision !== expectedRevision) throw new Error("report package revision mismatch");
  if (manifest.operational_revision !== expectedOperationalRevision) throw new Error("report package operational revision mismatch");
  const listed = new Set((manifest.files || []).map((item) => item?.ref).filter((item) => typeof item === "string"));
  const actual = collectRegularFileRefs(packagePath);
  actual.delete("package_manifest.json");
  if (listed.size !== actual.size || [...actual].some((item) => !listed.has(item))) {
    throw new Error("report package contents do not match its manifest");
  }
  return { package_ref: ref, manifest_ref: `${ref}/package_manifest.json`, manifest_digest: manifestDigest, file_count: listed.size };
}

function requireAct(root, value) {
  const actId = requireString(value, "actId", 128);
  if (!ACT_ID.test(actId)) throw new Error("actId must be a v4 ResearchAct ID");
  const registry = JSON.parse(readFileSync(resolve(root, "research_acts.json"), "utf8"));
  const matches = Array.isArray(registry.acts)
    ? registry.acts.filter((item) => isPlainObject(item) && item.act_id === actId)
    : [];
  if (matches.length !== 1) throw new Error(`unknown ResearchAct: ${actId}`);
  return actId;
}

function requireWorkspaceRoot(value) {
  if (typeof value !== "string" || !value || !isAbsolute(value)) throw new Error("workspace root must be absolute");
  const root = realpathSync(value);
  const workspace = JSON.parse(readFileSync(resolve(root, "workspace.json"), "utf8"));
  if (workspace.schema_version !== "ts-workspace/4") throw new Error("artifact tools require a v4 workspace");
  return root;
}

function collectRegularFileRefs(root) {
  const refs = new Set();
  const visit = (directory, prefix) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const ref = prefix ? `${prefix}/${entry.name}` : entry.name;
      const path = resolve(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`report package contains a symbolic link: ${ref}`);
      if (entry.isDirectory()) visit(path, ref);
      else if (entry.isFile()) refs.add(ref);
      else throw new Error(`report package contains a non-regular entry: ${ref}`);
    }
  };
  visit(root, "");
  return refs;
}

function assertWithin(root, candidate) {
  const rel = relative(root, candidate);
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) throw new Error("artifact path escapes workspace");
}

function assertNoSymlinkComponents(root, ref) {
  let current = root;
  for (const part of ref.split("/")) {
    current = resolve(current, part);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new Error(`artifact path traverses a symlink: ${ref}`);
  }
}

function sha256Bytes(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function requireDigest(value, label) {
  const digest = requireString(value, label, 71);
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label} must be a SHA-256 digest`);
  return digest;
}

function uniqueStrings(value, label, limit, pattern) {
  if (!Array.isArray(value) || value.length < 1 || value.length > limit) throw new Error(`${label} must contain 1-${limit} items`);
  const rows = value.map((item, index) => requireString(item, `${label}[${index}]`, 128));
  if (new Set(rows).size !== rows.length) throw new Error(`${label} contains duplicates`);
  if (rows.some((item) => !pattern.test(item))) throw new Error(`${label} contains an invalid ID`);
  return rows;
}

function requireEnum(value, label, allowed) {
  if (!allowed.includes(value)) throw new Error(`invalid ${label}: ${value}`);
  return value;
}

function requireString(value, label, maximum) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maximum) throw new Error(`${label} exceeds ${maximum} characters`);
  return text;
}

function rejectUnknownKeys(value, allowed, label) {
  const expected = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !expected.has(key));
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
};
