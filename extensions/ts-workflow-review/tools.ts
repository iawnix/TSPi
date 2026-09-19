import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PiRuntime, requireWorkspaceRoot } from "../adapters/pi-runtime.ts";
import {
  createPublicToolContracts,
  PUBLIC_TOOL_NAMES,
  type ReplyToolParams,
  type ReviewToolParams,
} from "../core/tools.mjs";
import {
  createSubagentStatusReporter,
  terminalStateForReport,
  terminalStatusForError,
} from "../shared/subagent-status.ts";
import {
  renderTsReviewCall,
  renderTsReviewResult,
} from "../shared/review-tool-presentation.ts";
import { runScientificReview } from "../../packages/ts-agent-runtime/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const EXTENSION_DIR = dirname(fileURLToPath(import.meta.url));
const { buildReviewTaskBundle, validateSubagentRequest } = require(resolve(EXTENSION_DIR, "..", "..", "packages", "ts-agent-runtime", "agents", "review", "task-packet.cjs"));
const { reviewSnapshotFromMap } = require(resolve(EXTENSION_DIR, "..", "..", "packages", "ts-agent-runtime", "agents", "review", "research-map-adapter.cjs"));
const {
  beginAgentRun,
  completeAgentRun,
  readAgentRunInputs,
  settleFailedAgentRun,
  writeInvalidReviewOutput,
  writeReviewRootDisposition,
} = require(resolve(EXTENSION_DIR, "..", "..", "packages", "ts-agent-runtime", "agent-core", "run-journal.cjs"));
const { classifyUpstreamModelFailure } = require(resolve(EXTENSION_DIR, "..", "..", "packages", "ts-agent-runtime", "agent-core", "failure-taxonomy.cjs"));
const { toolText } = require("../ts-workflow-control/summary.cjs");

const ROOT_DISPOSITIONS = ["accepted", "partially_accepted", "rejected", "deferred"] as const;
const TOOL_CONTRACTS = createPublicToolContracts(Type);

export function registerReviewTools(pi: ExtensionAPI) {
  const runtime = new PiRuntime(pi);
  pi.registerTool({
    ...TOOL_CONTRACTS.review,
    promptGuidelines: [
      "Use at ambiguity, failure analysis, branch selection, or final audit; advice is not evidence or a Claim conclusion.",
      `After success, call ${PUBLIC_TOOL_NAMES.reply} before scientific mutation.`,
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
    async execute(toolCallId, params: ReviewToolParams, signal, onUpdate, ctx) {
      if (!ctx.model) {
        throw new Error("No parent model is selected for TS subagent delegation");
      }
      const request = validateSubagentRequest({
        targetClaimRef: params.targetClaimRef,
        question: params.question,
        reviewerRole: params.reviewerRole,
        root: params.root,
        artifactIds: params.artifactIds,
      });
      const root = requireWorkspaceRoot(request.root, ctx.cwd);
      const taskId = await runtime.allocateId("sub", root, signal);
      const reportStatus = createSubagentStatusReporter({
        tool_call_id: toolCallId,
        task_id: taskId,
        role: "review",
        operation: "claim_review",
        target_ref: params.targetClaimRef,
        reviewer_role: request.reviewerRole,
      }, onUpdate);
      reportStatus("queued");
      const researchMap = await runtime.command("research.map", root, {}, signal);
      const reviewSnapshot = reviewSnapshotFromMap(researchMap, request.targetClaimRef);
        const artifactCatalog = request.artifactIds.length
          ? (await runtime.command("compute.artifacts", root, {}, signal)).artifacts
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
          tool: PUBLIC_TOOL_NAMES.reply,
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
    ...TOOL_CONTRACTS.reply,
    promptSnippet: "Record a TS Review disposition",
    promptGuidelines: [
      `Call after every successful ${PUBLIC_TOOL_NAMES.review} and before scientific mutation.`,
      "State what is adopted, rejected, or deferred and why; this response is not evidence.",
    ],
    async execute(_toolCallId, params: ReplyToolParams, _signal, _onUpdate, ctx) {
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
