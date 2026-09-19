import type { ToolCallEvent, ToolCallEventResult } from "@earendil-works/pi-coding-agent";
import { existsSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, relative, resolve } from "node:path";
import { PACKAGE_ROOT } from "../adapters/pi-runtime.ts";

export const PACKAGE_SOURCE_READ_TOOLS = ["read", "grep", "find", "ls"] as const;
export const PACKAGE_USAGE_GUIDELINE =
  "Use registered schemas, bounded context catalogs, and public Skill references; do not inspect installed implementation or tests during research.";

const PUBLIC_KNOWLEDGE_ROOT = resolve(
  PACKAGE_ROOT,
  "skills",
);

export function packageSourceSystemPrompt(): string {
  return [
    "Installed TS research runtime.",
    PACKAGE_USAGE_GUIDELINE,
    "Package maintenance belongs in the authored checkout.",
  ].join(" ");
}

export function guardPackageSourceRead(
  event: ToolCallEvent,
  cwd: string,
): ToolCallEventResult | undefined {
  if (!isPackageReadTool(event.toolName)) return undefined;
  const input = event.input as { path?: unknown };
  const rawPath = typeof input.path === "string" && input.path.trim()
    ? input.path.trim()
    : cwd;
  const target = resolveToolPath(rawPath, cwd);
  const packageRoot = canonicalPath(PACKAGE_ROOT);
  if (!isWithin(packageRoot, target)) return undefined;
  if (isWithin(canonicalPath(PUBLIC_KNOWLEDGE_ROOT), target)) return undefined;
  return {
    block: true,
    reason: [
      "TS package implementation and tests are not usage documentation in the installed research runtime.",
      "Use the registered tool schema, ts_state mode=artifacts or mode=capabilities,",
      "or the public skills/ references. Diagnose or change package implementation",
      "from the separate authored checkout, then build and install a validated release.",
    ].join(" "),
  };
}

function isPackageReadTool(name: string): name is typeof PACKAGE_SOURCE_READ_TOOLS[number] {
  return (PACKAGE_SOURCE_READ_TOOLS as readonly string[]).includes(name);
}

function resolveToolPath(value: string, cwd: string): string {
  let expanded = value;
  if (value === "~") expanded = homedir();
  else if (value.startsWith("~/")) expanded = resolve(homedir(), value.slice(2));
  const absolute = isAbsolute(expanded) ? resolve(expanded) : resolve(cwd, expanded);
  return canonicalPath(absolute);
}

function canonicalPath(path: string): string {
  if (!existsSync(path)) return resolve(path);
  try {
    return realpathSync.native(path);
  } catch (_error) {
    return resolve(path);
  }
}

function isWithin(root: string, target: string): boolean {
  const child = relative(root, target);
  return child === "" || (!child.startsWith("..") && !isAbsolute(child));
}
