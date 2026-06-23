import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const {
  buildContextSummary,
  parseJsonOutput,
  resolveWorkspaceRoot,
  toolText,
} = require("./summary.cjs");

const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = resolve(EXTENSION_DIR, "..", "..");
const WORKSPACE_CLI = resolve(PACKAGE_ROOT, "scripts", "ts_workspace.py");
const RUNTIME_MANIFEST = resolve(PACKAGE_ROOT, ".runtime", "env.json");
const ENVIRONMENT_SPEC = resolve(PACKAGE_ROOT, "environment.yml");

type TsCommand = "validate_decision" | "start_node" | "update_workspace" | "end_node";

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", async (event, ctx) => {
    const root = resolveWorkspaceRoot("", ctx.cwd);
    if (!root) {
      return;
    }
    try {
      const report = await runJson(pi, "report_workspace", root, [], ctx.signal);
      const summary = buildContextSummary(report);
      return {
        systemPrompt: `${event.systemPrompt}\n\n${summary}`,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        systemPrompt: `${event.systemPrompt}\n\nTS workspace context unavailable: ${message}`,
      };
    }
  });

  pi.registerTool({
    name: "ts_workspace_context",
    label: "TS Context",
    description: "Read the current transition-state workspace report and return a compact context summary.",
    promptSnippet: "Summarize the current transition-state workspace state from report_workspace",
    promptGuidelines: [
      "Use ts_workspace_context before choosing or closing a transition-state workflow node.",
      "Use ts_workspace_context instead of reading every workspace ledger when only current state is needed.",
    ],
    parameters: Type.Object({
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const report = await runJson(pi, "report_workspace", root, [], signal);
      const summary = buildContextSummary(report);
      return toolText(summary, { report });
    },
  });

  pi.registerTool({
    name: "ts_workspace_validate",
    label: "TS Validate",
    description: "Run validate_workspace for a transition-state workflow workspace.",
    promptSnippet: "Validate the transition-state workspace contract",
    promptGuidelines: [
      "Use ts_workspace_validate after mutation or before reporting a transition-state workflow conclusion.",
    ],
    parameters: Type.Object({
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const validation = await runJson(pi, "validate_workspace", root, [], signal);
      return toolText(JSON.stringify(validation, null, 2), { validation });
    },
  });

  pi.registerTool({
    name: "ts_workspace_decision",
    label: "TS Decision",
    description: "Apply or preflight a ts_workspace decision JSON through the public control plane.",
    promptSnippet: "Validate or apply a transition-state workspace decision JSON",
    promptGuidelines: [
      "Use ts_workspace_decision for transition-state workspace mutations; do not edit manifest, tree, node, evidence, mechanism, or pathway ledgers by hand.",
      "Use ts_workspace_decision with action=validate_decision before mutating when decision shape is uncertain.",
    ],
    parameters: Type.Object({
      action: StringEnum(["validate_decision", "start_node", "update_workspace", "end_node"] as const),
      decisionFile: Type.String({ description: "Path to a decision JSON file." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const decisionFile = resolve(ctx.cwd, String(params.decisionFile).replace(/^@+/, ""));
      const result = await runJson(pi, params.action as TsCommand, root, ["--decision-file", decisionFile], signal);
      return toolText(JSON.stringify(result, null, 2), { result });
    },
  });

  pi.registerCommand("ts-context", {
    description: "Show a compact transition-state workspace context summary.",
    handler: async (args, ctx) => {
      const root = requireWorkspaceRoot(args || "", ctx.cwd);
      const report = await runJson(pi, "report_workspace", root, [], ctx.signal);
      const summary = buildContextSummary(report);
      ctx.ui.setWidget("ts-workspace-context", summary.split("\n"));
      ctx.ui.notify("TS workspace context refreshed", "info");
    },
  });

  pi.registerCommand("ts-validate", {
    description: "Validate a transition-state workspace.",
    handler: async (args, ctx) => {
      const root = requireWorkspaceRoot(args || "", ctx.cwd);
      const validation = await runJson(pi, "validate_workspace", root, [], ctx.signal);
      const status = validation.valid ? "valid" : "invalid";
      ctx.ui.notify(`TS workspace ${status}`, validation.valid ? "info" : "warning");
      ctx.ui.setWidget("ts-workspace-validation", JSON.stringify(validation, null, 2).split("\n"));
    },
  });
}

async function runJson(pi: ExtensionAPI, command: string, root: string, extraArgs: string[], signal?: AbortSignal) {
  const result = await pi.exec(resolvePythonExecutable(), [WORKSPACE_CLI, command, "--root", root, ...extraArgs], { signal });
  return parseJsonOutput(result);
}

function resolvePythonExecutable(): string {
  if (process.env.TS_AGENT_PYTHON) {
    return process.env.TS_AGENT_PYTHON;
  }
  if (existsSync(RUNTIME_MANIFEST)) {
    try {
      const manifest = JSON.parse(readFileSync(RUNTIME_MANIFEST, "utf8"));
      if (
        manifest &&
        manifestMatchesSpec(manifest) &&
        typeof manifest.python_executable === "string" &&
        existsSync(manifest.python_executable)
      ) {
        return manifest.python_executable;
      }
    } catch (_error) {
      return "python3";
    }
  }
  return "python3";
}

function manifestMatchesSpec(manifest: { spec_sha256?: unknown }): boolean {
  if (typeof manifest.spec_sha256 !== "string") {
    return true;
  }
  if (!existsSync(ENVIRONMENT_SPEC)) {
    return false;
  }
  const digest = createHash("sha256").update(readFileSync(ENVIRONMENT_SPEC)).digest("hex");
  return digest === manifest.spec_sha256;
}

function requireWorkspaceRoot(inputRoot: string | undefined, cwd: string): string {
  const root = resolveWorkspaceRoot(inputRoot || "", cwd);
  if (!root) {
    throw new Error("No TS workspace root found. Pass root or set TS_WORKSPACE_ROOT.");
  }
  return root;
}
