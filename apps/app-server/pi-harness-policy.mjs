import { existsSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, relative, resolve } from "node:path";

// The retired ExtensionAPI path enforced this policy in its tool_call hook.
// The Harness has no ExtensionAPI, so keep the security boundary as a small,
// presentation-independent hook that can run for every client (TUI, phone,
// monitor, or another trusted client).
export const PACKAGE_READ_TOOLS = Object.freeze(["read", "grep", "find", "ls"]);

export function createPackageSourceReadGuard({
  packageRoot,
  cwd = process.cwd(),
  publicKnowledgeRoot = resolve(packageRoot, "skills"),
}) {
  const root = canonicalPath(packageRoot);
  const publicRoot = canonicalPath(publicKnowledgeRoot);
  return (event) => {
    if (!event || !PACKAGE_READ_TOOLS.includes(event.toolName)) return undefined;
    const args = event.args && typeof event.args === "object" && !Array.isArray(event.args) ? event.args : {};
    const rawPath = typeof args.path === "string" && args.path.trim() ? args.path.trim() : "";
    const target = resolveToolPath(rawPath || cwd, cwd);
    if (!isWithin(root, target) || isWithin(publicRoot, target)) return undefined;
    return {
      block: {
        reason: [
          "TS package implementation and tests are not usage documentation in the installed research runtime.",
          "Use the registered tool schema, research_read mode=artifacts or mode=capabilities,",
          "or the public skills/ references. Diagnose or change package implementation",
          "from the separate authored checkout, then build and install a validated release.",
        ].join(" "),
      },
    };
  };
}

function resolveToolPath(value, cwd) {
  let expanded = value;
  if (value === "~") expanded = homedir();
  else if (value.startsWith("~/")) expanded = resolve(homedir(), value.slice(2));
  return canonicalPath(isAbsolute(expanded) ? resolve(expanded) : resolve(cwd, expanded));
}

function canonicalPath(path) {
  if (!existsSync(path)) return resolve(path);
  try {
    return realpathSync.native(path);
  } catch {
    return resolve(path);
  }
}

function isWithin(root, target) {
  const child = relative(root, target);
  return child === "" || (!child.startsWith("..") && !isAbsolute(child));
}
