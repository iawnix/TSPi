import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { requireWorkspaceRoot, runWorkspaceJson } from "../shared/workspace-cli.ts";
import { runScientificReview } from "../../src/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const { buildTaskPacket, validateSubagentRequest } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agents", "review", "task-packet.cjs"));
const { beginAgentRun, completeAgentRun, failAgentRun } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agent-core", "run-journal.cjs"));
const { toolText } = require("../ts-workflow-context/summary.cjs");

const REVIEW_TYPES = ["mechanism", "candidate", "tsfreq", "connectivity", "final_audit", "program_failure"] as const;

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ts_workspace_subagent",
    label: "TS Scientific Review",
    description: "Run one fresh, tool-free Pi subagent for bounded advisory review of selected TS workspace evidence.",
    promptSnippet: "Delegate a bounded independent review of selected transition-state workspace evidence",
    promptGuidelines: [
      "Use ts_workspace_subagent only at an ambiguity, failure-analysis, branch-selection, or final-audit boundary where an independent review can change the next decision.",
      "Treat its output as advisory analysis, not registered evidence or an accepted/pathway verdict; reconcile it against primary artifacts before mutating the workspace.",
      "Select nodeId or fromNode+anchorNode and explicit evidenceRefs/artifactRefs to keep the review scoped.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      reviewType: StringEnum(REVIEW_TYPES),
      question: Type.String({ minLength: 1, maxLength: 4000, description: "Focused scientific or technical review question." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
      nodeId: Type.Optional(Type.String({ description: "Node whose compact report and evidence may be reviewed." })),
      fromNode: Type.Optional(Type.String({ description: "Current failure or branch trigger node for a backtrack comparison." })),
      anchorNode: Type.Optional(Type.String({ description: "Historical checkpoint paired with fromNode." })),
      evidenceRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 16 })),
      artifactRefs: Type.Optional(Type.Array(Type.String(), { maxItems: 4 })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 180, description: "Host timeout in seconds. Defaults to 90." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.model) {
        throw new Error("No parent model is selected for TS subagent delegation");
      }
      const request = validateSubagentRequest({
        reviewType: params.reviewType,
        question: params.question,
        root: params.root,
        nodeId: params.nodeId,
        fromNode: params.fromNode,
        anchorNode: params.anchorNode,
        evidenceRefs: params.evidenceRefs,
        artifactRefs: params.artifactRefs,
      });
      const root = requireWorkspaceRoot(request.root, ctx.cwd);
      const workspaceReport = await runWorkspaceJson(pi, "report_workspace", root, [], signal);
      const nodeContext = request.nodeId
        ? await runWorkspaceJson(pi, "report_node", root, ["--node-id", request.nodeId], signal)
        : null;
      const branchContext = request.fromNode
        ? await runWorkspaceJson(
            pi,
            "report_branch_context",
            root,
            ["--from-node", request.fromNode, "--anchor-node", request.anchorNode as string],
            signal,
          )
        : null;
      const packet = buildTaskPacket({
        runId: `sub_${randomUUID()}`,
        workspaceRoot: root,
        request,
        workspaceReport,
        nodeContext,
        branchContext,
      });
      const journal = beginAgentRun(root, packet);
      try {
        const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
          ? undefined
          : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
        const result = await runScientificReview({
          workspaceRoot: root,
          packet,
          parentModel: ctx.model,
          parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
          thinkingLevel: pi.getThinkingLevel(),
          timeoutMs: params.timeoutSeconds ? params.timeoutSeconds * 1000 : undefined,
          signal,
        });
        const runRef = completeAgentRun(journal, {
          actions: [],
          result: result.result,
          metadata: result.metadata,
        });
        const metadata = { ...result.metadata, run_ref: runRef };
        pi.appendEntry("ts-workspace-subagent-run", metadata);
        return toolText(JSON.stringify(result.result, null, 2), {
          result: result.result,
          run: metadata,
        });
      } catch (error) {
        const runRef = failAgentRun(journal, { actions: [], error });
        pi.appendEntry("ts-workspace-subagent-failed", {
          task_id: packet.task_id,
          review_type: packet.operation,
          run_ref: runRef,
        });
        throw error;
      }
    },
  });
}
