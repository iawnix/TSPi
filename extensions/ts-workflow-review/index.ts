import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { requireWorkspaceRoot, runWorkspaceJson } from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  createSubagentStatusReporter,
  terminalStateForReport,
  terminalStatusForError,
} from "../shared/subagent-status.ts";
import { runScientificReview } from "../../src/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const { buildTaskPacket, validateSubagentRequest } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agents", "review", "task-packet.cjs"));
const { beginAgentRun, completeAgentRun, failAgentRun } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agent-core", "run-journal.cjs"));
const { classifyUpstreamModelFailure } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agent-core", "failure-taxonomy.cjs"));
const { toolText } = require("../ts-workflow-control/summary.cjs");

const REVIEW_TYPES = ["mechanism", "candidate", "tsfreq", "connectivity", "final_audit", "program_failure"] as const;

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.subagentReview,
    label: "TS Review Subagent",
    description: "Run one fresh, tool-free Pi subagent for bounded advisory review of selected TS workspace evidence.",
    promptSnippet: "Delegate a bounded independent review of selected transition-state workspace evidence",
    promptGuidelines: [
      `Use ${TS_PUBLIC_TOOL_NAMES.subagentReview} only at an ambiguity, failure-analysis, branch-selection, or final-audit boundary where an independent review can change the next decision.`,
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
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const taskId = `sub_${randomUUID()}`;
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "review",
        operation: params.reviewType,
        node_id: params.nodeId || params.fromNode,
      }, onUpdate);
      reportStatus("queued");
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
        runId: taskId,
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
          onLifecycle: reportStatus,
        });
        const runRef = completeAgentRun(journal, {
          actions: [],
          result: result.result,
          metadata: result.metadata,
        });
        const metadata = { ...result.metadata, run_ref: runRef };
        pi.appendEntry("ts-workspace-subagent-run", metadata);
        reportStatus(terminalStateForReport(result.result), { run_ref: runRef });
        return toolText(JSON.stringify(result.result, null, 2), {
          result: result.result,
          run: metadata,
        });
      } catch (error) {
        const failure = classifyUpstreamModelFailure(error, { replaySafe: true }) || {
          failure_class: "review_operator_failed",
          failure_stage: "operator",
          failure_domain: "review_operator",
          upstream_status: null,
          retry_safe: true,
        };
        const runRef = failAgentRun(journal, { actions: [], error, metadata: failure });
        pi.appendEntry("ts-workspace-subagent-failed", {
          task_id: packet.task_id,
          review_type: packet.operation,
          ...failure,
          run_ref: runRef,
        });
        const terminal = terminalStatusForError(error);
        reportStatus(terminal.state, { failure_kind: terminal.failure_kind, run_ref: runRef });
        throw error;
      }
    },
  });
}
