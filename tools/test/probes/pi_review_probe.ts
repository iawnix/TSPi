import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { runScientificReview } from "../../../packages/ts-agent-runtime/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const { buildReviewTaskBundle } = require("../../../packages/ts-agent-runtime/agents/review/task-packet.cjs");

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-review-child", {
    description: "Run one recording-provider Review child session.",
    handler: async (args, ctx) => {
      const taskId = "sub_1";
      const claimId = "claim_1";
      const nodeId = "node_1";
      const phaseId = "phase_1";
      const artifactMode = args.trim() === "artifact";
      const artifactPath = "review-artifact.log";
      const artifactBytes = artifactMode ? readFileSync(resolve(ctx.cwd, artifactPath)) : null;
      const artifactDigest = artifactBytes
        ? `sha256:${createHash("sha256").update(artifactBytes).digest("hex")}`
        : null;
      const artifactId = artifactDigest ? `art_${artifactDigest.slice(7, 31)}` : null;
      const reviewSnapshot = {
        schema_version: "ts-review-snapshot/5",
        report_id: "rep_review_probe",
        workspace_revision: `sha256:${"1".repeat(64)}`,
        snapshot_id: `ctx_${"c".repeat(24)}`,
        target_claim_ref: claimId,
        phases: [{
          id: phaseId, type: "research_phase", created_at: "2026-09-18T00:00:00Z", metadata: {},
          title: "Probe phase", objective: "Contain the recording-provider Review probe.", node_ids: [nodeId],
        }],
        claims: [{
          id: claimId, type: "research_claim", created_at: "2026-09-18T00:00:00Z", metadata: {},
          statement: "The probe pathway is concerted.", status: "proposed", predictions: [], falsifiers: [],
          node_ids: [nodeId], finding_ids: [], gate_ids: [],
        }],
        claim_relations: [],
        nodes: [{
          id: nodeId, type: "research_node", created_at: "2026-09-18T00:00:00Z", metadata: {},
          title: "Review probe", objective: "Review the probe Claim.", phase_id: phaseId,
          claim_ids: [claimId], dependency_ids: [], finding_ids: [], gate_ids: [], attempt_refs: [],
          artifact_refs: artifactId ? [artifactId] : [], state: "active", outcome: null, outcome_summary: null,
        }],
        findings: [], gates: [],
        dependency_refs: {
          phase_refs: [phaseId], claim_refs: [claimId], relation_refs: [], node_refs: [nodeId],
          finding_refs: [], gate_refs: [],
        },
        omitted: {},
      };
      const artifactCatalog = artifactId && artifactDigest && artifactBytes ? [{
        artifact_id: artifactId, path: artifactPath, sha256: artifactDigest,
        size_bytes: statSync(resolve(ctx.cwd, artifactPath)).size, owner_node: nodeId, source_intent_id: null,
      }] : [];
      const bundle = buildReviewTaskBundle({
        runId: taskId,
        workspaceRoot: ctx.cwd,
        request: {
          targetClaimRef: claimId,
          question: "Assess whether the current bounded graph supports the probe Claim.",
          root: ctx.cwd,
          artifactIds: artifactId ? [artifactId] : [],
        },
        reviewSnapshot,
        artifactCatalog,
      });
      const packet = bundle.task;
      const boundSnapshot = bundle.documents.review_snapshot;
      const providerInput = bundle.documents.provider_input;
      try {
        const result = await runScientificReview({
          workspaceRoot: ctx.cwd,
          packet,
          reviewSnapshot: boundSnapshot,
          providerInput,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_REVIEW:${JSON.stringify(result)}`, "info");
      } catch (error) {
        const value = error && typeof error === "object" ? error as Record<string, unknown> : {};
        ctx.ui.notify(`TS_TEST_REVIEW_ERROR:${JSON.stringify({
          message: error instanceof Error ? error.message : String(error),
          actions: Array.isArray(value.reviewActions) ? value.reviewActions : [],
        })}`, "error");
      }
    },
  });
}
