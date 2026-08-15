import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createRequire } from "node:module";
import { runScientificReview } from "../src/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const { bindAgentDocument } = require("../src/agent-core/agent-protocol.cjs");
const { buildProviderTaskPacket } = require("../src/agents/review/task-packet.cjs");

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-review-child", {
    description: "Run one recording-provider v4 Review child session.",
    handler: async (_args, ctx) => {
      const taskId = "sub_review-probe";
      const claimId = `clm_${"a".repeat(24)}`;
      const actId = `act_${"b".repeat(24)}`;
      const revision = `sha256:${"1".repeat(64)}`;
      const scope = {
        report_id: "rep_review_probe",
        act_refs: [actId],
        claim_refs: [claimId],
      };
      const reviewSnapshot = {
        schema_version: "ts-review-task-snapshot/1",
        task_id: taskId,
        operation: "claim_review",
        scope,
        workspace_revision: revision,
        projection_id: `ctx_${"c".repeat(24)}`,
        target_claim_ref: claimId,
        claims: [{
          claim_id: claimId,
          claim_type: "mechanism",
          statement: "The probe pathway is concerted.",
          status: "proposed",
          assumptions: [],
          falsifiers: [],
          observation_refs: [],
          validation_spec_refs: [],
          validation_result_refs: [],
        }],
        claim_relations: [],
        research_acts: [{
          act_id: actId,
          objective: "Review the probe Claim.",
          status: "open",
          dependency_refs: [],
          claim_refs: [claimId],
          hypothesis: null,
          observation_refs: [],
          finding_refs: [],
          validation_spec_refs: [],
          validation_result_refs: [],
          result: null,
        }],
        observations: [],
        validation_specs: [],
        validation_results: [],
        findings: [],
        acceptances: [],
        dependency_refs: {
          claim_refs: [claimId],
          relation_refs: [],
          act_refs: [actId],
          observation_refs: [],
          validation_spec_refs: [],
          validation_result_refs: [],
          finding_refs: [],
          acceptance_refs: [],
        },
        artifact_excerpts: [],
        basis_allowlist: [actId, claimId].sort(),
        omitted: {},
      };
      const providerInput = buildProviderTaskPacket({
        task_id: taskId,
        objective: "Assess whether the current bounded graph supports the probe Claim.",
        review_snapshot: reviewSnapshot,
      });
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: taskId,
        role: "review",
        authority: "advisory",
        operation: "claim_review",
        objective: providerInput.objective,
        workspace: { root: ctx.cwd, report_id: scope.report_id, revision },
        scope,
        inputs: {
          review_snapshot: bindAgentDocument(
            "review-snapshot.json", "ts-review-task-snapshot/1", reviewSnapshot,
          ),
          provider_input: bindAgentDocument(
            "provider-input.json", "ts-review-provider-input/3", providerInput,
          ),
        },
        capabilities: ["ts_review_result"],
        constraints: {
          canonical_workspace_mutation: false,
          scientific_decision: false,
          recursive_delegation: false,
          remote_authority: "execution_mirror",
          external_side_effects: false,
        },
        output_contract: "ts-agent-result/1",
      };
      try {
        const result = await runScientificReview({
          workspaceRoot: ctx.cwd,
          packet,
          reviewSnapshot,
          providerInput,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_REVIEW:${JSON.stringify(result)}`, "info");
      } catch (error) {
        ctx.ui.notify(`TS_TEST_REVIEW_ERROR:${error instanceof Error ? error.message : String(error)}`, "error");
      }
    },
  });
}
