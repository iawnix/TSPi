import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { packageRoot as installedRoot } from "../platform/resources.mjs";
import { loadPi } from "../pi/source.mjs";

function ownedPath(root, value) {
  const path = resolve(root, value);
  const child = relative(root, path);
  if (!child || child.startsWith(`..${sep}`) || child === ".." || isAbsolute(child)) {
    throw new Error(`Resource escapes package: ${value}`);
  }
  return path;
}

async function regularTree(root, path, files) {
  const info = await lstat(path);
  if (info.isSymbolicLink()) throw new Error(`Managed resource must not be a symlink: ${relative(root, path)}`);
  if (info.isDirectory()) {
    for (const entry of await readdir(path)) await regularTree(root, join(path, entry), files);
  } else if (info.isFile()) {
    files.push(path);
  } else {
    throw new Error(`Managed resource is not a regular file: ${relative(root, path)}`);
  }
}

/** Integrity belongs to the installation; parsing and prompt syntax belong to Pi. */
export async function loadProductSkills({ packageRoot = installedRoot } = {}) {
  const [manifest, inventory, { loadSkills }] = await Promise.all([
    readFile(join(packageRoot, "package.json"), "utf8").then(JSON.parse),
    readFile(join(packageRoot, "config/resources.json"), "utf8").then(JSON.parse),
    loadPi("skills"),
  ]);
  if (inventory.schema_version !== "coragent-resources/1") throw new Error("Invalid resource inventory");
  const skillRoots = manifest.pi.skills.map(value => ownedPath(packageRoot, value));
  const resourceFiles = [];
  for (const root of skillRoots) {
    // Check ancestors as well as descendants so a replaced domains/ directory
    // cannot redirect the selected Skill tree outside the managed package.
    for (let parent = dirname(root); parent !== packageRoot; parent = dirname(parent)) {
      if ((await lstat(parent)).isSymbolicLink()) throw new Error("Managed resource parent must not be a symlink");
    }
    await regularTree(packageRoot, root, resourceFiles);
  }
  const promptFile = ownedPath(packageRoot, "prompts/coragent.md");
  await regularTree(packageRoot, dirname(promptFile), resourceFiles);
  if (!resourceFiles.includes(promptFile)) throw new Error("Managed system prompt is missing");
  for (const file of resourceFiles) {
    const key = relative(packageRoot, file).split(sep).join("/");
    const digest = `sha256:${createHash("sha256").update(await readFile(file)).digest("hex")}`;
    if (inventory.files[key] !== digest) throw new Error(`Managed resource digest mismatch: ${key}`);
  }
  const observed = new Set(resourceFiles.map(file => relative(packageRoot, file).split(sep).join("/")));
  const prefixes = [...skillRoots, dirname(promptFile)].map(path => `${relative(packageRoot, path).split(sep).join("/")}/`);
  for (const key of Object.keys(inventory.files)) {
    if (prefixes.some(prefix => key.startsWith(prefix)) && !observed.has(key)) {
      throw new Error(`Managed resource is missing: ${key}`);
    }
  }
  const loaded = loadSkills({ cwd: packageRoot, agentDir: packageRoot, skillPaths: skillRoots, includeDefaults: false });
  if (loaded.diagnostics.length) throw new Error(`Skill loading failed: ${loaded.diagnostics.map(item => item.message).join("; ")}`);
  const skills = loaded.skills.map(skill => ({
    ...skill,
    digest: inventory.files[relative(packageRoot, skill.filePath).split(sep).join("/")],
    provenance_schema: "coragent-skill-provenance/1",
  }));
  return { packageRoot, skillsRoot: packageRoot, skills, resourceFiles };
}
