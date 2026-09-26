import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import { resolve, relative, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { validateHarnessToolDefinition } from "../../packages/ts-agent-runtime/host-api/tools.mjs";

const MANIFEST_SCHEMA = "tspi-server-extensions/1";
const NAME_PATTERN = /^[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*$/u;
const TOOL_PATTERN = /^[a-z][a-z0-9_]*$/u;
const SCOPE_VALUES = new Set(["server", "client", "both"]);
const PERMISSIONS = new Set([
  "workspace.read",
  "workspace.write",
  "remote.submit",
  "model.delegate",
  "notify.send",
]);

/**
 * Load only package-owned server extensions selected by a signed-in-package
 * manifest. The loader deliberately accepts factories, not arbitrary Pi
 * ExtensionAPI modules: server code gets the host-owned tool context and the
 * client never gets an opportunity to upload or select executable code.
 */
export async function loadServerExtensions(options = {}) {
  const packageRoot = requireAbsoluteDirectory(options.packageRoot, "packageRoot");
  await assertRegularDirectory(packageRoot, "packageRoot");
  const manifestPath = resolveManifestPath(packageRoot, options.manifestPath);
  const manifest = await readManifest(manifestPath, packageRoot);
  const allowlist = resolveAllowlist(options.allowlist, manifest.extensions);
  const selected = manifest.extensions.filter((extension) => allowlist.has(extension.name));
  if (selected.length === 0) {
    throw new Error("TSPi server extension allowlist selected no extensions");
  }

  const names = new Set();
  const toolNames = new Set(Array.isArray(options.reservedToolNames) ? options.reservedToolNames : []);
  const extensionToolNames = new Set();
  const tools = [];
  const inventory = [];
  for (const descriptor of selected) {
    if (names.has(descriptor.name)) throw new Error(`duplicate server extension name: ${descriptor.name}`);
    names.add(descriptor.name);
    if (descriptor.scope === "client") {
      throw new Error(`server extension ${descriptor.name} has client-only scope`);
    }
    const entryPath = await resolveOwnedEntry(packageRoot, descriptor.entry, descriptor.name);
    await verifyDigest(entryPath, descriptor.sha256, descriptor.name);
    const module = await import(pathToFileURL(entryPath).href);
    if (typeof module.createServerExtension !== "function") {
      throw new Error(`server extension ${descriptor.name} must export createServerExtension()`);
    }
    const created = await module.createServerExtension(options.factoryOptions || {});
    const extensionTools = Array.isArray(created) ? created : created?.tools;
    if (!Array.isArray(extensionTools) || extensionTools.length === 0) {
      throw new Error(`server extension ${descriptor.name} returned no tools`);
    }
    const declaredTools = descriptor.tools;
    const actualTools = extensionTools.map((tool) => validateTool(tool, descriptor.name));
    const actualNames = actualTools.map((tool) => tool.name);
    if (actualNames.length !== declaredTools.length || actualNames.some((name, index) => name !== declaredTools[index])) {
      throw new Error(`server extension ${descriptor.name} tool inventory does not match its manifest`);
    }
    for (const tool of actualTools) {
      if (toolNames.has(tool.name)) throw new Error(`server tool name collision: ${tool.name}`);
      toolNames.add(tool.name);
      extensionToolNames.add(tool.name);
      tools.push(tool);
    }
    inventory.push(Object.freeze({
      name: descriptor.name,
      scope: descriptor.scope,
      entry: descriptor.entry,
      tools: Object.freeze([...actualNames]),
      permissions: Object.freeze([...descriptor.permissions]),
      sha256: descriptor.sha256,
    }));
  }
  if (Array.isArray(options.requiredToolNames)) {
    for (const name of options.requiredToolNames) {
      if (!extensionToolNames.has(name)) throw new Error(`server extension selection did not provide required tool: ${name}`);
    }
  }
  return Object.freeze({
    tools: Object.freeze(tools),
    inventory: Object.freeze(inventory),
    manifestPath,
  });
}

export async function readServerExtensionManifest(packageRoot, manifestPath) {
  const root = requireAbsoluteDirectory(packageRoot, "packageRoot");
  await assertRegularDirectory(root, "packageRoot");
  return readManifest(resolveManifestPath(root, manifestPath), root);
}

function resolveManifestPath(packageRoot, configured) {
  const candidate = configured
    ? resolve(packageRoot, configured)
    : resolve(packageRoot, "extensions/server/extensions.json");
  const relativePath = relative(packageRoot, candidate);
  if (relativePath.startsWith(`..${sep}`) || relativePath === ".." || relativePath.includes(`${sep}..${sep}`)) {
    throw new Error(`server extension manifest must stay inside package root: ${candidate}`);
  }
  return candidate;
}

async function readManifest(path, packageRoot) {
  let parsed;
  try {
    await assertOwnedParents(packageRoot, path);
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error("manifest must be a regular file");
    parsed = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new Error(`could not read TSPi server extension manifest: ${path}`, { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || parsed.schema_version !== MANIFEST_SCHEMA) {
    throw new Error(`invalid TSPi server extension manifest: ${path}`);
  }
  if (!Array.isArray(parsed.extensions) || parsed.extensions.length === 0) {
    throw new Error("TSPi server extension manifest must contain extensions");
  }
  const extensions = parsed.extensions.map((value) => validateDescriptor(value));
  const names = new Set(extensions.map((extension) => extension.name));
  if (names.size !== extensions.length) throw new Error("TSPi server extension manifest contains duplicate names");
  return Object.freeze({ schema_version: MANIFEST_SCHEMA, extensions: Object.freeze(extensions) });
}

function validateDescriptor(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid server extension descriptor");
  const name = value.name;
  const entry = value.entry;
  const scope = value.scope;
  const sha256 = value.sha256;
  if (typeof name !== "string" || !NAME_PATTERN.test(name)) throw new Error("server extension name is invalid");
  if (typeof entry !== "string" || !entry || entry.startsWith("/") || entry.includes("\\")) {
    throw new Error(`server extension ${name} entry must be a relative POSIX path`);
  }
  if (typeof scope !== "string" || !SCOPE_VALUES.has(scope)) throw new Error(`server extension ${name} scope is invalid`);
  if (typeof sha256 !== "string" || !/^sha256:[0-9a-f]{64}$/u.test(sha256)) {
    throw new Error(`server extension ${name} must declare a sha256 digest`);
  }
  if (!Array.isArray(value.tools) || value.tools.length === 0 || value.tools.some((tool) => typeof tool !== "string" || !TOOL_PATTERN.test(tool))) {
    throw new Error(`server extension ${name} must declare its tool names`);
  }
  if (!Array.isArray(value.permissions) || value.permissions.some((permission) => typeof permission !== "string" || !PERMISSIONS.has(permission))) {
    throw new Error(`server extension ${name} declares an unknown permission`);
  }
  return Object.freeze({
    name,
    entry,
    scope,
    sha256,
    tools: Object.freeze([...value.tools]),
    permissions: Object.freeze([...value.permissions]),
  });
}

function resolveAllowlist(configured, descriptors) {
  const values = configured === undefined
    ? (process.env.TSPI_SERVER_EXTENSIONS || "").split(",").map((value) => value.trim()).filter(Boolean)
    : Array.isArray(configured) ? configured : String(configured).split(",").map((value) => value.trim()).filter(Boolean);
  const names = new Set(values.length ? values : descriptors.map((descriptor) => descriptor.name));
  for (const name of names) {
    if (!descriptors.some((descriptor) => descriptor.name === name)) throw new Error(`server extension is not in the manifest: ${name}`);
  }
  return names;
}

async function resolveOwnedEntry(packageRoot, entry, name) {
  const path = resolve(packageRoot, entry);
  const relativePath = relative(packageRoot, path);
  if (relativePath.startsWith(`..${sep}`) || relativePath === "..") {
    throw new Error(`server extension ${name} escaped package root`);
  }
  let info;
  try {
    await assertOwnedParents(packageRoot, path);
    info = await lstat(path);
  } catch (error) {
    throw new Error(`server extension ${name} entry is unavailable: ${entry}`, { cause: error });
  }
  if (!info.isFile() || info.isSymbolicLink()) throw new Error(`server extension ${name} entry must be a regular file`);
  return path;
}

async function verifyDigest(path, expected, name) {
  const digest = `sha256:${createHash("sha256").update(await readFile(path)).digest("hex")}`;
  if (digest !== expected) throw new Error(`server extension ${name} integrity check failed`);
}

function validateTool(tool, extensionName) {
  try {
    return validateHarnessToolDefinition(tool, {
      source: `server extension ${extensionName} tool`,
      requireCanonical: true,
    });
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : String(error), { cause: error });
  }
}

async function assertRegularDirectory(path, label) {
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`${label} must be a regular directory`);
}

async function assertOwnedParents(root, target) {
  const relativePath = relative(root, target);
  let current = root;
  for (const segment of relativePath.split(sep).slice(0, -1)) {
    current = resolve(current, segment);
    const info = await lstat(current);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`server extension path contains a non-owned directory: ${current}`);
  }
}

function requireAbsoluteDirectory(value, label) {
  if (typeof value !== "string" || !value.startsWith("/")) throw new Error(`${label} must be an absolute path`);
  return resolve(value);
}
