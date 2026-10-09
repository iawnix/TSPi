import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { lstat, readFile, readdir } from "node:fs/promises";
import { delimiter, relative, resolve, sep, join } from "node:path";

const MANIFEST_SCHEMA = "tspi-extension/1";
const NAME_PATTERN = /^[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*$/u;
const TOOL_PATTERN = /^[a-z][a-z0-9_]*$/u;
const VALIDATOR_RESERVED_DESTINATIONS = new Set([
  "validator.py", "validator_inputs.json", "validator_result.json", "input_manifest.json",
  "spec.json", "receipt.json", "status.json", "logs", ".tspi",
]);
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
 * validated execution descriptors; code is never imported during discovery.
 */
export async function discoverInstalledExtensions(options = {}) {
  const paths = await resolveManifestPaths(options);
  const extensions = [];
  const names = new Set();
  const validatorIds = new Set(), profileIds = new Set(), executorIds = new Set();
  const skillNames = new Set();
  for (const manifestPath of paths) {
    const extension = await readExtensionManifest(manifestPath);
    if (names.has(extension.name)) throw new Error(`duplicate installed extension name: ${extension.name}`);
    names.add(extension.name);
    for (const [entries, seen, label] of [[extension.validators, validatorIds, "validator"], [extension.acceptance_profiles, profileIds, "acceptance profile"], [extension.executors, executorIds, "executor"]]) {
      for (const entry of entries) {
        const identity = `${entry.id}@${entry.version}`;
        if (seen.has(identity)) throw new Error(`duplicate installed ${label}: ${identity}`);
        seen.add(identity);
      }
    }
    for (const skill of extension.skills) {
      if (skill.name && skillNames.has(skill.name)) throw new Error(`duplicate installed skill name: ${skill.name}`);
      if (skill.name) skillNames.add(skill.name);
    }
    extensions.push(extension);
  }
  return Object.freeze({
    schema_version: "tspi-extension-catalog/1",
    manifests: Object.freeze([...paths]),
    extensions: Object.freeze(extensions),
    skillRoots: Object.freeze(extensions.flatMap((extension) => extension.skills.map((skill) => skill.path))),
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
  assertKnownKeys(parsed, new Set(["schema_version", "name", "version", "skills", "server", "validators", "acceptance_profiles", "executors"]), "extension manifest");
  const name = validateName(parsed.name, "extension");
  const version = validateVersion(parsed.version, `extension ${name}`);
  if (!Array.isArray(parsed.skills)) throw new Error(`extension ${name} skills must be an array`);
  const root = resolve(path, "..");
  const skills = [];
  for (const value of parsed.skills) skills.push(await validateSkill(value, root, name));
  if (parsed.executors !== undefined && !Array.isArray(parsed.executors)) throw new Error("executors must be an array");
  const executors = (parsed.executors || []).map(value => validateExecutor(value, root, skills));
  const validators = [];
  if (parsed.validators !== undefined && !Array.isArray(parsed.validators)) throw new Error("validators must be an array");
  for (const validator of parsed.validators || []) {
    assertKnownKeys(validator, new Set(["id", "version", "entry", "sha256", "backend", "resources", "input_contract", "requirements"]), "validator");
    validateExecutionRequirements(validator.requirements ?? {}, "python");
    if (!nonemptyString(validator.id) || !nonemptyString(validator.version)) throw new Error("validator identity is required");
    if (!nonemptyString(validator.backend)) throw new Error("validator backend binding is required");
    const entry = resolveOwnedPath(root, validator.entry, "validator entry");
    await assertRegularFile(entry, "validator entry");
    await verifyDigest(entry, validator.sha256, "validator");
    if (validator.resources !== undefined && (!validator.resources || typeof validator.resources !== "object" || Array.isArray(validator.resources))) throw new Error("validator resources must be an object");
    const destinations = new Set();
    for (const [destination, resource] of Object.entries(validator.resources || {})) {
      const target = relative(root, resolveOwnedPath(root, destination, "validator resource destination"));
      if (!target || VALIDATOR_RESERVED_DESTINATIONS.has(target.split(sep)[0]) || target.startsWith("input_")
          || [...destinations].some(previous => previous === target || previous.startsWith(target + sep) || target.startsWith(previous + sep))) throw new Error("invalid validator resource destination");
      destinations.add(target);
      assertKnownKeys(resource, new Set(["path", "sha256"]), "validator resource");
      const path = resolveOwnedPath(root, resource.path, "validator resource");
      await assertRegularFile(path, "validator resource");
      await verifyDigest(path, resource.sha256, "validator resource");
    }
    if (validator.input_contract !== undefined) {
      const contract = validator.input_contract;
      assertKnownKeys(contract, new Set(["schema_version", "roles"]), "validator input contract");
      if (contract.schema_version !== "validator-input/1" || !Array.isArray(contract.roles) || !contract.roles.length) throw new Error("invalid validator input contract");
      const roles = new Set();
      for (const role of contract.roles) {
        assertKnownKeys(role, new Set(["name", "source", "schema_version", "max_bytes"]), "validator input role");
        if (!nonemptyString(role.name) || roles.has(role.name) || !["registered_artifact", "collected_output"].includes(role.source)
            || role.schema_version !== undefined && !nonemptyString(role.schema_version)
            || role.max_bytes !== undefined && (!Number.isInteger(role.max_bytes) || role.max_bytes < 1)) throw new Error("invalid validator input role");
        roles.add(role.name);
      }
    }
    validators.push(Object.freeze({ ...validator, entry }));
  }
  const acceptanceProfiles = [];
  if (parsed.acceptance_profiles !== undefined && !Array.isArray(parsed.acceptance_profiles)) throw new Error("acceptance_profiles must be an array");
  for (const profile of parsed.acceptance_profiles || []) {
    assertKnownKeys(profile, new Set(["id", "version", "description", "checks", "subject_binding", "binding_keys", "constraint_keys"]), "acceptance profile");
    if (!nonemptyString(profile.id) || !nonemptyString(profile.version)
        || profile.description !== undefined && !nonemptyString(profile.description)
        || profile.subject_binding !== undefined && !nonemptyString(profile.subject_binding)
        || !Array.isArray(profile.checks) || !profile.checks.length) throw new Error("invalid acceptance profile");
    const checkIds = new Set();
    for (const check of profile.checks) {
      assertKnownKeys(check, new Set(["id", "kind", "validator_id", "validator_version"]), "acceptance check");
      if (!nonemptyString(check.id) || checkIds.has(check.id) || !["validator_result", "registered_artifact"].includes(check.kind)
          || check.validator_id !== undefined && !nonemptyString(check.validator_id)
          || check.validator_version !== undefined && !nonemptyString(check.validator_version)
          || check.kind === "validator_result" && (!check.validator_id || !check.validator_version)) throw new Error("invalid acceptance check");
      checkIds.add(check.id);
    }
    for (const key of ["binding_keys", "constraint_keys"]) {
      if (profile[key] !== undefined && (!Array.isArray(profile[key]) || profile[key].some(value => !nonemptyString(value))
          || new Set(profile[key]).size !== profile[key].length)) throw new Error("invalid acceptance profile keys");
    }
    acceptanceProfiles.push(Object.freeze(profile));
  }
  const server = parsed.server === undefined ? undefined : await validateServer(parsed.server, root, name);
  return Object.freeze({
    schema_version: MANIFEST_SCHEMA,
    name,
    version,
    manifestPath: path,
    manifestDigest: `sha256:${createHash("sha256").update(await readFile(path)).digest("hex")}`,
    root,
    skills: Object.freeze(skills),
    executors: Object.freeze(executors),
    validators: Object.freeze(validators),
    acceptance_profiles: Object.freeze(acceptanceProfiles),
    ...(server ? { server } : {}),
  });
}

async function resolveManifestPaths(options) {
  const configured = options.manifestPaths === undefined
    ? (process.env.TSPI_EXTENSION_MANIFESTS || "").split(delimiter).map((value) => value.trim()).filter(Boolean)
    : Array.isArray(options.manifestPaths) ? options.manifestPaths : [options.manifestPaths];
  const paths = configured.map((value) => requireAbsoluteFile(value, "extension manifest"));
  // Core Skills are part of the installed Harness, including when optional
  // domain manifests are supplied from outside the package.
  if (options.packageRoot) {
    const core = join(requireAbsoluteFile(options.packageRoot, "package root"), "extensions", "core", "manifest.json");
    try {
      const info = await lstat(core);
      if (!info.isFile() || info.isSymbolicLink()) throw new Error("core manifest must be a regular file");
      paths.unshift(core);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
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
  assertKnownKeys(value, new Set(["name", "path", "sha256", "resources_sha256"]), `extension ${extensionName} Skill`);
  const path = resolveOwnedPath(root, value.path, `extension ${extensionName} Skill`);
  await assertRegularDirectory(path, `extension ${extensionName} Skill`);
  const skillFile = resolve(path, "SKILL.md");
  await assertRegularFile(skillFile, `extension ${extensionName} Skill`);
  const name = value.name === undefined ? undefined : validateName(value.name, `extension ${extensionName} Skill`);
  if (value.sha256 !== undefined) await verifyDigest(skillFile, value.sha256, `extension ${extensionName} Skill`);
  const resourceFiles = [];
  const resourceDigests = {};
  if (value.resources_sha256 !== undefined) {
    const indexPath = join(path, "resources.json");
    await assertRegularFile(indexPath, `Skill ${name} resource index`);
    await verifyDigest(indexPath, value.resources_sha256, `Skill ${name} resource index`);
    const index = JSON.parse(await readFile(indexPath, "utf8"));
    if (index.schema_version !== "skill-resources/1" || index.base !== "extension"
      || !index.files || typeof index.files !== "object" || Array.isArray(index.files)) throw new Error("invalid Skill resource index");
    for (const [file, hash] of Object.entries(index.files)) {
      const resource = resolveOwnedPath(root, file, `Skill ${name} resource`);
      await assertOwnedParents(resource);
      await assertRegularFile(resource, `Skill ${name} resource`);
      await verifyDigest(resource, hash, `Skill ${name} resource`);
      resourceFiles.push(resource);
      resourceDigests[file] = hash;
    }
  }
  return Object.freeze({ name, path, file: skillFile, resourceFiles: Object.freeze(resourceFiles), resourceDigests: Object.freeze(resourceDigests), ...(value.sha256 === undefined ? {} : { sha256: value.sha256 }) });
}

function validateExecutionRequirements(value, runtime) {
  assertKnownKeys(value, new Set(["python", "packages", "imports"]), "execution requirements");
  if (runtime === "native" && Object.keys(value).length) throw new Error("native execution cannot require Python");
  if (value.python !== undefined && !nonemptyString(value.python)) throw new Error("invalid Python requirement");
  if (value.packages !== undefined && (!value.packages || typeof value.packages !== "object" || Array.isArray(value.packages)
      || Object.entries(value.packages).some(([name, spec]) => !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/u.test(name) || !nonemptyString(spec)))) throw new Error("invalid package requirements");
  if (value.imports !== undefined && (!Array.isArray(value.imports) || new Set(value.imports).size !== value.imports.length
      || value.imports.some(name => typeof name !== "string" || !/^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/u.test(name)))) throw new Error("invalid import requirements");
}

function validateExecutor(value, root, skills) {
  assertKnownKeys(value, new Set(["id", "version", "skill", "backend", "runtime", "entry", "cli", "argv", "inputs", "outputs", "requirements"]), "executor");
  if (!nonemptyString(value.id) || !nonemptyString(value.version) || !nonemptyString(value.backend)
      || !["python", "native"].includes(value.runtime)) throw new Error("invalid executor identity/binding");
  validateExecutionRequirements(value.requirements ?? {}, value.runtime);
  const skill = skills.find(row => row.name === value.skill);
  if (!skill) throw new Error("executor must reference an installed Skill");
  for (const key of ["entry", "cli"]) {
    if (value[key] === undefined) continue;
    const resource = resolveOwnedPath(root, value[key], `executor ${key}`);
    if (!skill.resourceFiles.includes(resource)) throw new Error(`executor ${key} must be a pinned Skill resource`);
  }
  if (value.runtime === "python" && !value.entry) throw new Error("Python executor requires an entry");
  if (value.runtime === "native" && value.entry !== undefined) throw new Error("native executor uses the configured command");
  const inputs = value.inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) throw new Error("executor inputs must be an object");
  const destinations = new Set(Object.keys(skill.resourceDigests));
  for (const [role, destination] of Object.entries(inputs)) {
    if (!/^[a-z][a-z0-9_]*$/u.test(role)) throw new Error("invalid executor input role");
    const target = relative(root, resolveOwnedPath(root, destination, "executor input"));
    if (!target || target !== destination || ["spec.json", "receipt.json", "status.json", "input_manifest.json", "logs", ".tspi"].includes(target.split(sep)[0])
        || [...destinations].some(previous => previous === target || previous.startsWith(target + sep) || target.startsWith(previous + sep))) throw new Error("executor input destinations overlap or are reserved");
    destinations.add(target);
  }
  if (!Array.isArray(value.argv) || !value.argv.length || value.argv.some(arg => !nonemptyString(arg))) throw new Error("invalid executor argv");
  const placeholders = new Set(["{entry}", "{args}", "{command}", "{executable}", ...Object.keys(inputs).map(role => `{input:${role}}`)]);
  for (const token of value.argv) {
    if ((token.startsWith("{") || token.endsWith("}")) && !placeholders.has(token)) throw new Error("unknown executor argv placeholder");
  }
  if (value.argv[0] !== (value.runtime === "python" ? "{entry}" : "{command}")
      || value.argv.filter(token => token === "{args}").length > 1) throw new Error("invalid executor command template");
  if (!Array.isArray(value.outputs)) throw new Error("executor outputs must be an array");
  const outputs = new Set();
  for (const output of value.outputs) {
    assertKnownKeys(output, new Set(["path", "required", "min_bytes", "media_type", "recursive"]), "executor output");
    const target = relative(root, resolveOwnedPath(root, output.path, "executor output"));
    if (!target || target !== output.path || outputs.has(target)
        || typeof output.required !== "boolean" || !Number.isInteger(output.min_bytes) || output.min_bytes < 0
        || output.recursive !== undefined && typeof output.recursive !== "boolean"
        || output.media_type !== undefined && !nonemptyString(output.media_type)) throw new Error("invalid executor output");
    outputs.add(target);
  }
  return Object.freeze(value);
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
  if (relativePath.split("/").includes("..")) throw new Error(`${label} path escaped extension root`);
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
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be an object`);
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) throw new Error(`${label} contains unknown field: ${unknown[0]}`);
}

function nonemptyString(value) {
  return typeof value === "string" && value.length > 0;
}

function requireAbsoluteFile(value, label) {
  if (typeof value !== "string" || !value.startsWith("/")) throw new Error(`${label} must be an absolute path`);
  return resolve(value);
}

// Python consumers use this exact discovery/validation boundary as well.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const packageRoot = process.argv[2] || resolve(fileURLToPath(new URL("../..", import.meta.url)));
    process.stdout.write(JSON.stringify(await discoverInstalledExtensions({ packageRoot })));
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
