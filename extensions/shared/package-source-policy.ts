import type { ToolCallEvent, ToolCallEventResult } from "@earendil-works/pi-coding-agent";
import { existsSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, relative, resolve } from "node:path";
import { PACKAGE_ROOT } from "./workspace-cli.ts";

export const PACKAGE_SOURCE_READ_TOOLS = ["read", "grep", "find", "ls"] as const;
export const PACKAGE_USAGE_GUIDELINE =
  "Use registered tool schemas and prompt guidelines for call shape, ts_workspace_context modes for live artifacts and capabilities, and the public transition-state Skill references for operating guidance. Do not inspect package implementation or tests to learn ordinary tool usage.";

const PUBLIC_KNOWLEDGE_ROOT = resolve(
  PACKAGE_ROOT,
  "skills",
  "transition-state-workflow",
);

export function packageSourceSystemPrompt(): string {
  return [
    "TS package knowledge policy: installed research runtime.",
    PACKAGE_USAGE_GUIDELINE,
    "Package reads are limited to the public transition-state Skill, its references, and its assets. Package implementation work belongs in the separate authored checkout, not this research session.",
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
      "Use the registered tool schema, ts_workspace_context mode=artifacts or mode=capabilities,",
      "or skills/transition-state-workflow references. Diagnose or change package implementation",
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
