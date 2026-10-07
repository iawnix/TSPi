import { dirname, resolve, relative, isAbsolute } from "node:path";

/** Explicit registered-name reads avoid assuming an extension's folder layout. */
export function createSkillPathResolver(skills) {
  const registry = new Map(skills.map(skill => [skill.name, skill.filePath]));
  return function resolveSkillPath(args) {
    if (typeof args?.path !== "string" || !args.path.startsWith("skill:")) return args;
    const match = /^skill:([a-z0-9-]+)(?:\/(.*))?$/.exec(args.path);
    const file = match && registry.get(match[1]);
    if (!file) throw new Error(`Unknown registered Skill: ${args.path}. Available: ${[...registry.keys()].join(", ")}`);
    const root = dirname(file);
    const path = match[2] ? resolve(root, match[2]) : file;
    const rel = relative(root, path);
    if (isAbsolute(rel) || rel === ".." || rel.startsWith("../")) throw new Error("Skill resource must remain inside its registered directory");
    return { ...args, path };
  };
}
