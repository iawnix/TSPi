import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { delimiter, relative, resolve, sep, join } from "node:path";

const MANIFEST_SCHEMA = "tspi-extension/1";
const NAME_PATTERN = /^[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*$/u;
const PROVIDER_ID_PATTERN = /^[a-z][a-z0-9]*(?:[-._][a-z0-9]+)*$/u;
const PROVIDER_KINDS = new Set(["compute", "analysis", "harness", "notification", "render", "report"]);
const TOOL_PATTERN = /^[a-z][a-z0-9_]*$/u;
const SERVER_PERMISSIONS = new Set([
  "workspace.read",
  "workspace.write",
  "remote.submit",
  "model.delegate",
  "notify.send",
]);

/**
 * Discover installed extension manifests without importing extension code.
 *
 * The package core only supplies the registry shape. An installer supplies
 * absolute manifest paths through TSPI_EXTENSION_MANIFESTS (or the explicit
 * `manifestPaths` option). Each manifest owns its Skill directories and
 * provider metadata; execution adapters remain a separate trusted boundary.
 */
export async function discoverInstalledExtensions(options = {}) {
  const paths = await resolveManifestPaths(options);
  const extensions = [];
  const names = new Set();
  const providerIds = new Set();
  const skillNames = new Set();
  for (const manifestPath of paths) {
    const extension = await readExtensionManifest(manifestPath);
    if (names.has(extension.name)) throw new Error(`duplicate installed extension name: ${extension.name}`);
    names.add(extension.name);
    for (const provider of extension.providers) {
      if (providerIds.has(provider.id)) throw new Error(`duplicate installed provider id: ${provider.id}`);
      providerIds.add(provider.id);
    }
    for (const skill of extension.skills) {
      if (skill.name && skillNames.has(skill.name)) throw new Error(`duplicate installed skill name: ${skill.name}`);
      if (skill.name) skillNames.add(skill.name);
    }
    extensions.push(extension);
  }
  return Object.freeze({
    manifests: Object.freeze([...paths]),
    extensions: Object.freeze(extensions),
    skillRoots: Object.freeze(extensions.flatMap((extension) => extension.skills.map((skill) => skill.path))),
    providers: Object.freeze(extensions.flatMap((extension) => extension.providers)),
  });
}

export async function readExtensionManifest(manifestPath) {
  const path = requireAbsoluteFile(manifestPath, "extension manifest");
  let parsed;
  try {
    await assertOwnedParents(path);
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error("manifest must be a regular file");
    parsed = JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    throw new Error(`could not read TSPi extension manifest: ${path}`, { cause: error });
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || parsed.schema_version !== MANIFEST_SCHEMA) {
    throw new Error(`invalid TSPi extension manifest: ${path}`);
  }
  assertKnownKeys(parsed, new Set(["schema_version", "name", "version", "skills", "providers", "server"]), "extension manifest");
  const name = validateName(parsed.name, "extension");
  const version = validateVersion(parsed.version, `extension ${name}`);
  if (!Array.isArray(parsed.skills)) throw new Error(`extension ${name} skills must be an array`);
  if (!Array.isArray(parsed.providers)) throw new Error(`extension ${name} providers must be an array`);
  const root = resolve(path, "..");
  const skills = [];
  for (const value of parsed.skills) skills.push(await validateSkill(value, root, name));
  const providers = [];
  for (const value of parsed.providers) providers.push(await validateProvider(value, root, name));
  const server = parsed.server === undefined ? undefined : await validateServer(parsed.server, root, name);
  return Object.freeze({
    schema_version: MANIFEST_SCHEMA,
    name,
    version,
    manifestPath: path,
    root,
    skills: Object.freeze(skills),
    providers: Object.freeze(providers),
    ...(server ? { server } : {}),
  });
}

async function resolveManifestPaths(options) {
  const configured = options.manifestPaths === undefined
    ? (process.env.TSPI_EXTENSION_MANIFESTS || "").split(delimiter).map((value) => value.trim()).filter(Boolean)
    : Array.isArray(options.manifestPaths) ? options.manifestPaths : [options.manifestPaths];
  const paths = configured.map((value) => requireAbsoluteFile(value, "extension manifest"));
  if (options.packageRoot && options.manifestPaths === undefined && !process.env.TSPI_EXTENSION_MANIFESTS && !configured.length) {
    const extensionsRoot = join(requireAbsoluteFile(options.packageRoot, "package root"), "extensions");
    const packageManifest = join(extensionsRoot, "manifest.json");
    try {
      const info = await lstat(packageManifest);
      if (!info.isFile() || info.isSymbolicLink()) throw new Error(`package extension manifest must be a regular file: ${packageManifest}`);
      paths.push(packageManifest);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      let entries;
      try {
        entries = await readdir(extensionsRoot, { withFileTypes: true });
      } catch (directoryError) {
        if (directoryError?.code === "ENOENT") return [];
        throw directoryError;
      }
      for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
        if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
        const manifest = join(extensionsRoot, entry.name, "manifest.json");
        try {
          const manifestInfo = await lstat(manifest);
          if (manifestInfo.isFile() && !manifestInfo.isSymbolicLink()) paths.push(manifest);
        } catch (manifestError) {
          if (manifestError?.code !== "ENOENT") throw manifestError;
        }
      }
    }
  }
  return [...new Set(paths)];
}

async function validateSkill(value, root, extensionName) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`extension ${extensionName} has an invalid Skill descriptor`);
  assertKnownKeys(value, new Set(["name", "path", "sha256"]), `extension ${extensionName} Skill`);
  const path = resolveOwnedPath(root, value.path, `extension ${extensionName} Skill`);
  await assertRegularDirectory(path, `extension ${extensionName} Skill`);
  const skillFile = resolve(path, "SKILL.md");
  await assertRegularFile(skillFile, `extension ${extensionName} Skill`);
  const name = value.name === undefined ? undefined : validateName(value.name, `extension ${extensionName} Skill`);
  if (value.sha256 !== undefined) await verifyDigest(skillFile, value.sha256, `extension ${extensionName} Skill`);
  return Object.freeze({ name, path, file: skillFile, ...(value.sha256 === undefined ? {} : { sha256: value.sha256 }) });
}

async function validateProvider(value, root, extensionName) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`extension ${extensionName} has an invalid provider descriptor`);
  assertKnownKeys(value, new Set(["id", "version", "kind", "descriptor", "descriptor_sha256", "entry", "sha256"]), `extension ${extensionName} provider`);
  const id = value.id;
  if (typeof id !== "string" || !PROVIDER_ID_PATTERN.test(id)) throw new Error(`extension ${extensionName} provider id is invalid`);
  const version = validateVersion(value.version, `provider ${id}`);
  if (typeof value.kind !== "string" || !PROVIDER_KINDS.has(value.kind)) throw new Error(`extension ${extensionName} provider ${id} kind is invalid`);
  const descriptor = value.descriptor === undefined ? undefined : resolveOwnedPath(root, value.descriptor, `provider ${id} descriptor`);
  const entry = value.entry === undefined ? undefined : resolveOwnedPath(root, value.entry, `provider ${id} entry`);
  if (!descriptor && !entry) throw new Error(`extension ${extensionName} provider ${id} must declare descriptor or entry`);
  let descriptorData;
  let descriptorDigest;
  if (descriptor) {
    await assertRegularFile(descriptor, `provider ${id} descriptor`);
    if (value.descriptor_sha256 !== undefined) await verifyDigest(descriptor, value.descriptor_sha256, `provider ${id} descriptor`);
    try {
      const descriptorBytes = await readFile(descriptor);
      descriptorDigest = `sha256:${createHash("sha256").update(descriptorBytes).digest("hex")}`;
      descriptorData = JSON.parse(descriptorBytes.toString("utf8"));
    } catch (error) {
      throw new Error(`provider ${id} descriptor is not valid JSON`, { cause: error });
    }
    if (!descriptorData || typeof descriptorData !== "object" || Array.isArray(descriptorData)) {
      throw new Error(`provider ${id} descriptor must contain an object`);
    }
  }
  if (entry) {
    await assertRegularFile(entry, `provider ${id} entry`);
    if (value.sha256 === undefined) throw new Error(`provider ${id} entry must declare sha256`);
    await verifyDigest(entry, value.sha256, `provider ${id}`);
  }
  return Object.freeze({
    id,
    version,
    kind: value.kind,
    ...(descriptor ? { descriptor } : {}),
    ...(descriptorData ? { descriptor_data: Object.freeze(descriptorData) } : {}),
    ...(descriptorDigest ? { descriptor_digest: descriptorDigest } : {}),
    ...(entry ? { entry } : {}),
    ...(value.sha256 === undefined ? {} : { sha256: value.sha256 }),
    ...(value.descriptor_sha256 === undefined ? {} : { descriptor_sha256: value.descriptor_sha256 }),
  });
}

async function validateServer(value, root, extensionName) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`extension ${extensionName} has an invalid server descriptor`);
  assertKnownKeys(value, new Set(["entry", "sha256", "tools", "permissions"]), `extension ${extensionName} server`);
  const entry = resolveOwnedPath(root, value.entry, `extension ${extensionName} server`);
  if (typeof value.sha256 !== "string" || !/^sha256:[0-9a-f]{64}$/u.test(value.sha256)) {
    throw new Error(`extension ${extensionName} server must declare a sha256 digest`);
  }
  if (!Array.isArray(value.tools) || value.tools.length === 0 || value.tools.some((tool) => typeof tool !== "string" || !TOOL_PATTERN.test(tool))) {
    throw new Error(`extension ${extensionName} server must declare its tool names`);
  }
  if (new Set(value.tools).size !== value.tools.length) throw new Error(`extension ${extensionName} server contains duplicate tool names`);
  if (!Array.isArray(value.permissions) || value.permissions.some((permission) => typeof permission !== "string" || !SERVER_PERMISSIONS.has(permission))) {
    throw new Error(`extension ${extensionName} server declares an unknown permission`);
  }
  if (new Set(value.permissions).size !== value.permissions.length) throw new Error(`extension ${extensionName} server contains duplicate permissions`);
  await assertRegularFile(entry, `extension ${extensionName} server`);
  await verifyDigest(entry, value.sha256, `extension ${extensionName} server`);
  return Object.freeze({
    entry,
    sha256: value.sha256,
    tools: Object.freeze([...value.tools]),
    permissions: Object.freeze([...value.permissions]),
  });
}

function resolveOwnedPath(root, relativePath, label) {
  if (typeof relativePath !== "string" || !relativePath || relativePath.startsWith("/") || relativePath.includes("\\")) {
    throw new Error(`${label} path must be a relative POSIX path`);
  }
  const path = resolve(root, relativePath);
  const escaped = relative(root, path);
  if (escaped.startsWith(`..${sep}`) || escaped === ".." || escaped.includes(`${sep}..${sep}`)) {
    throw new Error(`${label} path escaped extension root`);
  }
  return path;
}

async function assertOwnedParents(target) {
  const relativePath = relative(sep, target);
  let current = sep;
  for (const segment of relativePath.split(sep).slice(0, -1)) {
    current = resolve(current, segment);
    const info = await lstat(current);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`extension path contains a non-owned directory: ${current}`);
  }
}

async function assertRegularDirectory(path, label) {
  try {
    const info = await lstat(path);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`${label} path must be a regular directory`);
  } catch (error) {
    throw new Error(`${label} path is unavailable: ${path}`, { cause: error });
  }
}

async function assertRegularFile(path, label) {
  try {
    await assertOwnedParents(path);
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink()) throw new Error(`${label} must be a regular file`);
  } catch (error) {
    throw new Error(`${label} is unavailable: ${path}`, { cause: error });
  }
}

async function verifyDigest(path, expected, label) {
  if (typeof expected !== "string" || !/^sha256:[0-9a-f]{64}$/u.test(expected)) throw new Error(`${label} digest must be sha256:<64 hex>`);
  const digest = `sha256:${createHash("sha256").update(await readFile(path)).digest("hex")}`;
  if (digest !== expected) throw new Error(`${label} integrity check failed`);
}

function validateName(value, label) {
  if (typeof value !== "string" || !NAME_PATTERN.test(value)) throw new Error(`${label} name is invalid`);
  return value;
}

function validateVersion(value, label) {
  if (typeof value !== "string" || !/^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.-]+)?$/u.test(value)) throw new Error(`${label} version is invalid`);
  return value;
}

function assertKnownKeys(value, allowed, label) {
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) throw new Error(`${label} contains unknown field: ${unknown[0]}`);
}

function requireAbsoluteFile(value, label) {
  if (typeof value !== "string" || !value.startsWith("/")) throw new Error(`${label} must be an absolute path`);
  return resolve(value);
}
