"use strict";

const {
  closeSync,
  fstatSync,
  openSync,
  readSync,
  realpathSync,
  statSync,
} = require("node:fs");
const { createHash } = require("node:crypto");
const path = require("node:path");

const ARTIFACT_READ_TOOL_NAME = "ts_review_artifact_read";
const ARTIFACT_EXTRACTOR_VERSION = "ts-review-artifact-extractor/1";
const TEXT_EXTENSIONS = new Set([".com", ".gjf", ".inp", ".json", ".log", ".md", ".out", ".txt", ".xyz"]);
const MAX_READ_REQUESTS = 6;
const MAX_EXCERPT_BYTES = 4 * 1024;
const MAX_TOTAL_EXCERPT_BYTES = 12 * 1024;
const MAX_SEMANTIC_SOURCE_BYTES = 64 * 1024 * 1024;
const MAX_SECTION_RANGES = 32;

const COMMON_SECTIONS = Object.freeze(["head", "tail"]);
const SECTIONS_BY_TYPE = Object.freeze({
  gaussian_output: Object.freeze([
    "overview",
    "route",
    "termination",
    "optimization",
    "frequencies",
    "final_geometry",
    "irc",
    "diagnostics",
    ...COMMON_SECTIONS,
  ]),
  gaussian_input: Object.freeze(["input", ...COMMON_SECTIONS]),
  structure_xyz: Object.freeze(["structure", ...COMMON_SECTIONS]),
  json_document: Object.freeze(["document", ...COMMON_SECTIONS]),
  text_document: Object.freeze(["document", "overview", "diagnostics", ...COMMON_SECTIONS]),
});

function buildArtifactManifest({ workspaceRoot, artifactIds, researchMap, artifactCatalog }) {
  if (!artifactIds.length) return [];
  if (!Array.isArray(artifactCatalog)) throw new Error("Review artifact catalog must be an array");
  const root = realpathSync(workspaceRoot);
  const allowed = researchMapArtifactRefs(researchMap);
  const catalog = new Map(artifactCatalog.filter(isPlainObject).map((item) => [item.artifact_id, item]));

  const manifest = artifactIds.map((artifactId) => {
    if (!allowed.has(artifactId)) throw new Error(`Review artifact is outside the Claim dependency graph: ${artifactId}`);
    const item = catalog.get(artifactId);
    if (!isPlainObject(item)) throw new Error(`Review artifact is unavailable in the workspace catalog: ${artifactId}`);
    const artifactPath = normalizeRelativeRef(item.path);
    const artifactType = artifactTypeForPath(artifactPath);
    const file = verifyArtifactFile(root, {
      artifact_id: artifactId,
      path: artifactPath,
      sha256: requireDigest(item.sha256, `artifact ${artifactId} sha256`),
      size_bytes: requireNonnegativeInteger(item.size_bytes, `artifact ${artifactId} size_bytes`),
    });
    return {
      artifact_id: artifactId,
      path: artifactPath,
      sha256: file.sha256,
      size_bytes: file.size_bytes,
      owner_node: nullableBoundedString(item.owner_node, `artifact ${artifactId} owner_node`, 128),
      source_intent_id: nullableBoundedString(item.source_intent_id, `artifact ${artifactId} source_intent_id`, 256),
      artifact_type: artifactType,
      available_sections: [...SECTIONS_BY_TYPE[artifactType]],
    };
  });
  return validateArtifactManifest(manifest);
}

function validateArtifactManifestOwnership(value, researchMap) {
  const manifest = validateArtifactManifest(value);
  const allowed = researchMapArtifactRefs(researchMap);
  for (const item of manifest) {
    if (!allowed.has(item.artifact_id)) {
      throw new Error(`Review artifact is outside the Claim dependency graph: ${item.artifact_id}`);
    }
  }
  return manifest;
}

function validateArtifactManifest(value) {
  if (!Array.isArray(value) || value.length > 4) {
    throw new Error("Review artifact manifest must be an array with at most 4 entries");
  }
  const seen = new Set();
  return value.map((item, index) => {
    if (!isPlainObject(item)) throw new Error(`Review artifact manifest entry ${index} must be an object`);
    rejectUnknownKeys(item, [
      "artifact_id",
      "path",
      "sha256",
      "size_bytes",
      "owner_node",
      "source_intent_id",
      "artifact_type",
      "available_sections",
    ], `Review artifact manifest entry ${index}`);
    const artifactId = requireArtifactId(item.artifact_id, `artifact manifest entry ${index} artifact_id`);
    if (seen.has(artifactId)) throw new Error(`Review artifact manifest contains duplicate ID: ${artifactId}`);
    seen.add(artifactId);
    const artifactPath = normalizeRelativeRef(item.path);
    const expectedType = artifactTypeForPath(artifactPath);
    if (item.artifact_type !== expectedType) throw new Error(`Review artifact type does not match its file: ${artifactId}`);
    const expectedSections = [...SECTIONS_BY_TYPE[expectedType]];
    if (JSON.stringify(item.available_sections) !== JSON.stringify(expectedSections)) {
      throw new Error(`Review artifact sections do not match its type: ${artifactId}`);
    }
    return {
      artifact_id: artifactId,
      path: artifactPath,
      sha256: requireDigest(item.sha256, `artifact ${artifactId} sha256`),
      size_bytes: requireNonnegativeInteger(item.size_bytes, `artifact ${artifactId} size_bytes`),
      owner_node: nullableBoundedString(item.owner_node, `artifact ${artifactId} owner_node`, 128),
      source_intent_id: nullableBoundedString(item.source_intent_id, `artifact ${artifactId} source_intent_id`, 256),
      artifact_type: expectedType,
      available_sections: expectedSections,
    };
  });
}

function reviewArtifactReferences(value) {
  return validateArtifactManifest(value).map((item) => ({
    artifact_id: item.artifact_id,
    artifact_type: item.artifact_type,
    sha256: item.sha256,
    size_bytes: item.size_bytes,
    owner_node: item.owner_node,
    source_intent_id: item.source_intent_id,
    available_sections: item.available_sections,
  }));
}

function readArtifactSections({ workspaceRoot, artifactManifest, requests }) {
  let root;
  try {
    root = realpathSync(workspaceRoot);
  } catch {
    throw new Error("Review workspace is unavailable during artifact read");
  }
  const manifest = validateArtifactManifest(artifactManifest);
  const normalizedRequests = validateReadRequests(requests, manifest);
  const perExcerptBudget = Math.min(
    MAX_EXCERPT_BYTES,
    Math.floor(MAX_TOTAL_EXCERPT_BYTES / normalizedRequests.length),
  );
  const byId = new Map(manifest.map((item) => [item.artifact_id, item]));
  const sources = new Map();

  return normalizedRequests.map((request) => {
    const artifact = byId.get(request.artifact_id);
    let source = sources.get(request.artifact_id);
    if (!source) {
      source = readVerifiedText(root, artifact);
      sources.set(request.artifact_id, source);
    }
    return extractSection(artifact, source, request.section, perExcerptBudget);
  });
}

function validateReadRequests(value, manifest) {
  if (!Array.isArray(value) || value.length < 1 || value.length > MAX_READ_REQUESTS) {
    throw new Error(`Review artifact read requires 1 to ${MAX_READ_REQUESTS} requests`);
  }
  const byId = new Map(manifest.map((item) => [item.artifact_id, item]));
  const seen = new Set();
  return value.map((item, index) => {
    if (!isPlainObject(item)) throw new Error(`Review artifact read request ${index} must be an object`);
    rejectUnknownKeys(item, ["artifact_id", "section"], `Review artifact read request ${index}`);
    const artifactId = requireArtifactId(item.artifact_id, `artifact read request ${index} artifact_id`);
    const artifact = byId.get(artifactId);
    if (!artifact) throw new Error(`Review artifact is not available to this task: ${artifactId}`);
    const section = requireString(item.section, `artifact read request ${index} section`, 64);
    if (!artifact.available_sections.includes(section)) {
      throw new Error(`Review artifact section is unavailable for ${artifactId}: ${section}`);
    }
    const key = `${artifactId}\u0000${section}`;
    if (seen.has(key)) throw new Error(`Review artifact read request is duplicated: ${artifactId}/${section}`);
    seen.add(key);
    return { artifact_id: artifactId, section };
  });
}

function researchMapArtifactRefs(researchMap) {
  if (!isPlainObject(researchMap) || researchMap.schema_version !== "research-map/1"
      || !Array.isArray(researchMap.nodes) || !Array.isArray(researchMap.findings)) {
    throw new Error("Review artifact selection requires ResearchMap Nodes and Findings");
  }
  const allowed = new Set();
  for (const node of researchMap.nodes) {
    for (const artifactId of Array.isArray(node?.artifact_refs) ? node.artifact_refs : []) {
      if (typeof artifactId === "string" && artifactId) allowed.add(artifactId);
    }
  }
  for (const finding of researchMap.findings) {
    for (const artifactId of Array.isArray(finding?.source_refs) ? finding.source_refs : []) {
      if (typeof artifactId === "string" && artifactId) allowed.add(artifactId);
    }
  }
  return allowed;
}

function verifyArtifactFile(root, artifact) {
  const realArtifact = resolveArtifactFile(root, artifact);
  const stat = statSync(realArtifact);
  if (stat.size !== artifact.size_bytes) throw new Error(`Review artifact size changed: ${artifact.artifact_id}`);
  const sha256 = hashFile(realArtifact);
  if (sha256 !== artifact.sha256) throw new Error(`Review artifact content changed: ${artifact.artifact_id}`);
  return { path: realArtifact, size_bytes: stat.size, sha256 };
}

function resolveArtifactFile(root, artifact) {
  try {
    const absolute = path.resolve(root, artifact.path);
    assertInside(root, absolute, `Review artifact path escapes workspace: ${artifact.artifact_id}`);
    const realRoot = realpathSync(root);
    const realArtifact = realpathSync(absolute);
    assertInside(realRoot, realArtifact, `Review artifact symlink escapes workspace: ${artifact.artifact_id}`);
    const stat = statSync(realArtifact);
    if (!stat.isFile()) throw new Error(`Review artifact is not a regular file: ${artifact.artifact_id}`);
    return realArtifact;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Review artifact")) throw error;
    throw new Error(`Review artifact is unavailable: ${artifact.artifact_id}`);
  }
}

function readVerifiedText(root, artifact) {
  const realArtifact = resolveArtifactFile(root, artifact);
  let descriptor;
  try {
    descriptor = openSync(realArtifact, "r");
  } catch {
    throw new Error(`Review artifact is unavailable: ${artifact.artifact_id}`);
  }
  let buffer;
  try {
    const before = fstatSync(descriptor);
    if (before.size !== artifact.size_bytes) throw new Error(`Review artifact size changed: ${artifact.artifact_id}`);
    if (before.size > MAX_SEMANTIC_SOURCE_BYTES) {
      throw new Error(`Review artifact exceeds the semantic reader limit: ${artifact.artifact_id}`);
    }
    buffer = Buffer.alloc(before.size);
    let position = 0;
    while (position < before.size) {
      const bytesRead = readSync(descriptor, buffer, position, before.size - position, position);
      if (bytesRead < 1) throw new Error(`Review artifact changed while reading: ${artifact.artifact_id}`);
      position += bytesRead;
    }
    const after = fstatSync(descriptor);
    if (after.size !== before.size) throw new Error(`Review artifact size changed while reading: ${artifact.artifact_id}`);
  } finally {
    closeSync(descriptor);
  }
  const sha256 = `sha256:${createHash("sha256").update(buffer).digest("hex")}`;
  if (sha256 !== artifact.sha256) throw new Error(`Review artifact content changed: ${artifact.artifact_id}`);
  if (buffer.includes(0)) throw new Error(`Review artifact contains binary data: ${artifact.artifact_id}`);
  const text = buffer.toString("utf8");
  return {
    lines: text.length
      ? text.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n")
      : [],
    size_bytes: buffer.length,
    sha256,
  };
}

function extractSection(artifact, source, section, maxBytes) {
  const ranges = sectionRanges(source.lines, section);
  const rendered = renderRanges(source.lines, ranges);
  const excerpt = truncateUtf8(rendered, maxBytes);
  const excerptBytes = Buffer.byteLength(excerpt.text, "utf8");
  return {
    schema_version: "ts-review-artifact-excerpt/1",
    artifact_id: artifact.artifact_id,
    section,
    found: ranges.length > 0,
    source_sha256: source.sha256,
    source_size_bytes: source.size_bytes,
    extractor_version: ARTIFACT_EXTRACTOR_VERSION,
    line_ranges: ranges.map(([start, end]) => ({ start: start + 1, end: end + 1 })),
    excerpt_sha256: `sha256:${createHash("sha256").update(excerpt.text).digest("hex")}`,
    excerpt_bytes: excerptBytes,
    truncated: ranges.length > 0
      && (excerpt.truncated || !coversWholeDocument(ranges, source.lines.length)),
    text: excerpt.text,
  };
}

function sectionRanges(lines, section) {
  if (!lines.length) return [];
  if (section === "head") return [[0, Math.min(lines.length - 1, 159)]];
  if (section === "tail") return [[Math.max(0, lines.length - 160), lines.length - 1]];
  if (["document", "input", "structure"].includes(section)) return [[0, lines.length - 1]];
  if (section === "overview") {
    return mergeRanges([
      [0, Math.min(lines.length - 1, 24)],
      [Math.max(0, lines.length - 40), lines.length - 1],
    ]);
  }
  if (section === "route") return routeRanges(lines);
  if (section === "final_geometry") return finalGeometryRanges(lines);
  const patterns = {
    termination: /Normal termination|Error termination|Job cpu time|Elapsed time/i,
    optimization: /Stationary point found|Optimization completed|Optimization stopped|Maximum Force|RMS\s+Force|Maximum Displacement|RMS\s+Displacement/i,
    frequencies: /Frequencies --|imaginary frequencies|Zero-point correction|Thermal correction|Sum of electronic and thermal/i,
    irc: /Point Number|NET REACTION COORDINATE|Reaction path following|PES minimum|IRC-IRC-IRC/i,
    diagnostics: /Error termination|QPErr|Convergence failure|segmentation fault|l9999|No such file|Erroneous write|Killed|\bwarning\b/i,
  };
  const pattern = patterns[section];
  return pattern ? contextRanges(lines, pattern, 2, 2) : [];
}

function routeRanges(lines) {
  const start = lines.findIndex((line) => /^\s*#\s*\S/.test(line));
  if (start < 0) return [];
  let end = Math.min(lines.length - 1, start + 24);
  for (let index = start + 1; index <= end; index += 1) {
    if (/^\s*-{5,}\s*$/.test(lines[index])) {
      end = index;
      break;
    }
  }
  return [[start, end]];
}

function finalGeometryRanges(lines) {
  let start = -1;
  for (let index = 0; index < lines.length; index += 1) {
    if (/^\s*(Standard|Input) orientation:\s*$/.test(lines[index])) start = index;
  }
  if (start < 0) return [];
  let delimiters = 0;
  let end = Math.min(lines.length - 1, start + 220);
  for (let index = start + 1; index <= end; index += 1) {
    if (/^\s*-{5,}\s*$/.test(lines[index])) {
      delimiters += 1;
      if (delimiters === 3) {
        end = index;
        break;
      }
    }
  }
  return [[start, end]];
}

function contextRanges(lines, pattern, before, after) {
  const ranges = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (pattern.test(lines[index])) {
      ranges.push([Math.max(0, index - before), Math.min(lines.length - 1, index + after)]);
    }
  }
  return boundRanges(mergeRanges(ranges));
}

function boundRanges(ranges) {
  if (ranges.length <= MAX_SECTION_RANGES) return ranges;
  const half = MAX_SECTION_RANGES / 2;
  return [...ranges.slice(0, half), ...ranges.slice(-half)];
}

function mergeRanges(ranges) {
  const sorted = ranges
    .filter(([start, end]) => Number.isInteger(start) && Number.isInteger(end) && start <= end)
    .sort((left, right) => left[0] - right[0]);
  const merged = [];
  for (const range of sorted) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1] + 1) previous[1] = Math.max(previous[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

function renderRanges(lines, ranges) {
  return ranges.map(([start, end]) => {
    const header = `[lines ${start + 1}-${end + 1}]`;
    return `${header}\n${lines.slice(start, end + 1).join("\n")}`;
  }).join("\n\n");
}

function truncateUtf8(value, maxBytes) {
  const source = Buffer.from(value, "utf8");
  if (source.length <= maxBytes) return { text: value, truncated: false };
  const text = source.subarray(0, maxBytes).toString("utf8").replace(/\uFFFD+$/g, "");
  return { text, truncated: true };
}

function coversWholeDocument(ranges, lineCount) {
  return ranges.length === 1 && ranges[0][0] === 0 && ranges[0][1] === lineCount - 1;
}

function artifactTypeForPath(value) {
  const extension = path.posix.extname(value).toLowerCase();
  if (!TEXT_EXTENSIONS.has(extension)) throw new Error("Review artifact is not an allowlisted text type");
  const basename = path.posix.basename(value).toLowerCase();
  if ((extension === ".out" || extension === ".log") && basename.startsWith("gaussian")) return "gaussian_output";
  if (extension === ".gjf" || extension === ".com") return "gaussian_input";
  if (extension === ".xyz") return "structure_xyz";
  if (extension === ".json") return "json_document";
  return "text_document";
}

function hashFile(value) {
  const digest = createHash("sha256");
  const descriptor = openSync(value, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    const size = fstatSync(descriptor).size;
    let position = 0;
    while (position < size) {
      const bytesRead = readSync(descriptor, buffer, 0, Math.min(buffer.length, size - position), position);
      if (bytesRead < 1) throw new Error("Review artifact changed while hashing");
      digest.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
  } finally {
    closeSync(descriptor);
  }
  return `sha256:${digest.digest("hex")}`;
}

function normalizeRelativeRef(value) {
  const text = requireString(value, "artifact path", 4096).replaceAll("\\", "/");
  if (path.posix.isAbsolute(text)) throw new Error("artifact path must be workspace-relative");
  const normalized = path.posix.normalize(text);
  if (normalized === "." || normalized === ".." || normalized.startsWith("../")) throw new Error("invalid artifact path");
  return normalized;
}

function assertInside(root, candidate, message) {
  const relative = path.relative(root, candidate);
  if (!relative || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) throw new Error(message);
}

function requireArtifactId(value, label) {
  const artifactId = requireString(value, label, 28);
  if (!/^art_[0-9a-f]{24}$/.test(artifactId)) throw new Error(`${label} is invalid`);
  return artifactId;
}

function requireDigest(value, label) {
  const digest = requireString(value, label, 71);
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label} must be a SHA-256 digest`);
  return digest;
}

function requireNonnegativeInteger(value, label) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} must be a nonnegative integer`);
  return value;
}

function nullableBoundedString(value, label, maxLength) {
  return value === null || value === undefined ? null : requireString(value, label, maxLength);
}

function requireString(value, label, maxLength) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a non-empty string`);
  const text = value.trim();
  if (text.length > maxLength) throw new Error(`${label} exceeds ${maxLength} characters`);
  return text;
}

function rejectUnknownKeys(value, allowed, label) {
  const known = new Set(allowed);
  const unknown = Object.keys(value).filter((key) => !known.has(key));
  if (unknown.length) throw new Error(`${label} contains unknown fields: ${unknown.join(", ")}`);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  ARTIFACT_EXTRACTOR_VERSION,
  ARTIFACT_READ_TOOL_NAME,
  MAX_EXCERPT_BYTES,
  MAX_READ_REQUESTS,
  MAX_TOTAL_EXCERPT_BYTES,
  SECTIONS_BY_TYPE,
  buildArtifactManifest,
  readArtifactSections,
  reviewArtifactReferences,
  validateArtifactManifest,
  validateArtifactManifestOwnership,
};
