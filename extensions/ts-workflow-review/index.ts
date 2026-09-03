import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { allocateOperationalId, requireWorkspaceRoot, runComputeJson, runWorkspaceJson } from "../shared/workspace-cli.ts";
import { TS_PUBLIC_TOOL_NAMES } from "../shared/tool-catalog.ts";
import {
  createSubagentStatusReporter,
  terminalStateForReport,
  terminalStatusForError,
} from "../shared/subagent-status.ts";
import {
  renderTsReviewCall,
  renderTsReviewResult,
} from "../shared/review-tool-presentation.ts";
import { runScientificReview } from "../../src/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const { buildReviewTaskBundle, validateSubagentRequest } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agents", "review", "task-packet.cjs"));
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
  writeInvalidReviewOutput,
  writeReviewRootDisposition,
} = require(resolve(EXTENSION_DIR, "..", "..", "src", "agent-core", "run-journal.cjs"));
const { classifyUpstreamModelFailure } = require(resolve(EXTENSION_DIR, "..", "..", "src", "agent-core", "failure-taxonomy.cjs"));
const { toolText } = require("../ts-workflow-control/summary.cjs");

const ROOT_DISPOSITIONS = ["accepted", "partially_accepted", "rejected", "deferred"] as const;

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.review,
    label: "TS Review Subagent",
    description: "Run one isolated advisory Review of a target Claim.",
    promptSnippet: "Review one TS Claim independently",
    promptGuidelines: [
      "Use at ambiguity, failure analysis, branch selection, or final audit; advice is not evidence or acceptance.",
      `After success, call ${TS_PUBLIC_TOOL_NAMES.reply} before scientific mutation.`,
      "Select one Claim; optional artifact IDs must already be cited in its derived graph. Paths are forbidden.",
    ],
    renderShell: "self",
    renderCall: (args, theme) => renderTsReviewCall(args as Record<string, unknown>, theme),
    renderResult: (result, options, theme, context) => renderTsReviewResult(
      result,
      options,
      theme,
      context.isError,
    ),
    executionMode: "sequential",
    parameters: Type.Object({
      targetClaimRef: Type.String({ minLength: 1, maxLength: 256, description: "Scientific claim that the Review must assess." }),
      question: Type.String({ minLength: 1, maxLength: 4000, description: "Focused scientific or technical review question." }),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
      artifactIds: Type.Optional(Type.Array(Type.String({ pattern: "^art_[0-9a-f]{24}$" }), { maxItems: 4, uniqueItems: true })),
      timeoutSeconds: Type.Optional(Type.Integer({ minimum: 1, maximum: 180, description: "Host timeout in seconds. Defaults to 90." })),
    }),
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      if (!ctx.model) {
        throw new Error("No parent model is selected for TS subagent delegation");
      }
      const request = validateSubagentRequest({
        targetClaimRef: params.targetClaimRef,
        question: params.question,
        root: params.root,
        artifactIds: params.artifactIds,
      });
      const root = requireWorkspaceRoot(request.root, ctx.cwd);
      const taskId = await allocateOperationalId(pi, "sub", root, signal);
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "review",
        operation: "claim_review",
        target_ref: params.targetClaimRef,
      }, onUpdate);
      reportStatus("queued");
      const snapshotArgs = ["--target-claim-ref", request.targetClaimRef];
      const reviewSnapshot = await runWorkspaceJson(pi, "build_review_snapshot", root, snapshotArgs, signal);
      const artifactCatalog = request.artifactIds.length
        ? (await runComputeJson(pi, "list-artifacts", root, [], signal)).artifacts
        : [];
      const bundle = buildReviewTaskBundle({
        runId: taskId,
        workspaceRoot: root,
        request,
        reviewSnapshot,
        artifactCatalog,
      });
      const packet = bundle.task;
      reportStatus("starting", {
        node_refs: packet.scope.node_refs,
        claim_refs: packet.scope.claim_refs,
      });
      const journal = beginAgentRun(root, packet, {
        documents: bundle.documents,
        ownerClaimRef: request.targetClaimRef,
      });
      const persisted = readAgentRunInputs(journal);
      try {
        const parentAuth = ctx.modelRegistry.isUsingOAuth(ctx.model)
          ? undefined
          : await ctx.modelRegistry.getApiKeyAndHeaders(ctx.model);
        const result = await runScientificReview({
          workspaceRoot: root,
          packet: persisted.task,
          reviewSnapshot: persisted.documents.review_snapshot,
          providerInput: persisted.documents.provider_input,
          parentModel: ctx.model,
          parentApiKey: parentAuth?.ok ? parentAuth.apiKey : undefined,
          thinkingLevel: pi.getThinkingLevel(),
          timeoutMs: params.timeoutSeconds ? params.timeoutSeconds * 1000 : undefined,
          signal,
          onLifecycle: reportStatus,
        });
        if (result.invalidOutputs.length) writeInvalidReviewOutput(journal, result.invalidOutputs);
        const runRef = completeAgentRun(journal, {
          actions: result.actions,
          result: result.result,
          metadata: result.metadata,
        });
        const metadata = { ...result.metadata, run_ref: runRef };
        pi.appendEntry("ts-workspace-subagent-run", metadata);
        reportStatus(terminalStateForReport(result.result), { run_ref: runRef });
        const obligation = {
          required: true,
          task_id: packet.task_id,
          review_run_ref: runRef,
          tool: TS_PUBLIC_TOOL_NAMES.reply,
          allowed_dispositions: ROOT_DISPOSITIONS,
        };
        return toolText(
          `${JSON.stringify(result.result, null, 2)}\n\nRoot response required before further workspace mutation:\n${JSON.stringify(obligation, null, 2)}`,
          {
            result: result.result,
            run: metadata,
            root_disposition: obligation,
          },
        );
      } catch (error) {
        const invalidOutputs = error && typeof error === "object"
          && Array.isArray((error as { invalidReviewOutputs?: unknown[] }).invalidReviewOutputs)
          ? (error as { invalidReviewOutputs: unknown[] }).invalidReviewOutputs
          : [];
        const actions = error && typeof error === "object"
          && Array.isArray((error as { reviewActions?: unknown[] }).reviewActions)
          ? (error as { reviewActions: unknown[] }).reviewActions
          : [];
        if (invalidOutputs.length) writeInvalidReviewOutput(journal, invalidOutputs);
        let failure = classifyUpstreamModelFailure(error, { replaySafe: true }) || {
          failure_class: "review_runtime_failed",
          failure_stage: "review_runtime",
          failure_domain: "review",
          upstream_status: null,
          retry_safe: true,
        };
        const settlement = settleFailedAgentRun(journal, { actions, error, metadata: failure });
        const runRef = settlement.run_ref || journal.runRef;
        if (settlement.journal_error) {
          failure = {
            ...failure,
            agent_journal_status: "pending",
            agent_journal_error: settlement.journal_error,
          };
        }
        pi.appendEntry("ts-workspace-subagent-failed", {
          task_id: packet.task_id,
          operation: packet.operation,
          ...failure,
          run_ref: runRef,
        });
        const terminal = terminalStatusForError(error);
        reportStatus(terminal.state, { failure_kind: terminal.failure_kind, run_ref: runRef });
        throw error;
      }
    },
  });

  pi.registerTool({
    name: TS_PUBLIC_TOOL_NAMES.reply,
    label: "TS Review Response",
    description: "Record Root's write-once response to a completed Review.",
    promptSnippet: "Record a TS Review disposition",
    promptGuidelines: [
      `Call after every successful ${TS_PUBLIC_TOOL_NAMES.review} and before scientific mutation.`,
      "State what is adopted, rejected, or deferred and why; this response is not evidence.",
    ],
    executionMode: "sequential",
    parameters: Type.Object({
      taskId: Type.String({ minLength: 1, maxLength: 160, description: "Exact task_id returned by ts_review." }),
      reviewRunRef: Type.String({ minLength: 1, maxLength: 512, description: "Exact review_run_ref returned by ts_review." }),
      disposition: StringEnum(ROOT_DISPOSITIONS),
      response: Type.String({ minLength: 1, maxLength: 4000, description: "Concise Root assessment of the advisory Review." }),
      nextSteps: Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { maxItems: 8 })),
      root: Type.Optional(Type.String({ description: "Workspace root. Defaults to TS_WORKSPACE_ROOT or nearest workspace ancestor." })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const root = requireWorkspaceRoot(params.root, ctx.cwd);
      const disposition = writeReviewRootDisposition(root, {
        task_id: params.taskId,
        review_run_ref: params.reviewRunRef,
        disposition: params.disposition,
        response: params.response,
        next_steps: params.nextSteps,
      });
      pi.appendEntry("ts-review-root-disposition", disposition);
      return toolText(JSON.stringify(disposition, null, 2), { disposition });
    },
  });
}
