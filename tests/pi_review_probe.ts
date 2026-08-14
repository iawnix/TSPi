import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createRequire } from "node:module";
import { runScientificReview } from "../src/agents/review/runtime.ts";

const require = createRequire(import.meta.url);
const { bindAgentDocument } = require("../src/agent-core/agent-protocol.cjs");

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-review-child", {
    description: "Run one tool-free recording-provider review child session.",
    handler: async (_args, ctx) => {
      const scope = {
        report_id: "rep_review_001",
        node_ids: ["n000"],
        claim_refs: ["claim_probe_001"],
      };
      const evidenceSnapshot = {
        schema_version: "ts-review-evidence-snapshot/2",
        task_id: "agent_review_001",
        operation: "claim_review",
        scope,
        target_claim_ref: "claim_probe_001",
        workspace_revision: "sha256:" + "2".repeat(64),
        claims: [{
          claim_id: "claim_probe_001",
          created_in_node: "n000",
          kind: "reaction_path/1",
          statement: "Probe claim.",
          status: "proposed",
          required_gates: [],
          evidence_refs: [],
          gate_result_refs: [],
          details: {},
          history: [],
        }],
        gate_results: [],
        evidence: [],
        nodes: [{ node_id: "n000", parent_node: null, objective: "Probe", state: "closed", tags: [], result: null }],
        artifact_excerpts: [],
        basis_allowlist: ["claim_probe_001"],
      };
      const providerInput = {
        schema_version: "ts-review-provider-input/2",
        task_id: "agent_review_001",
        operation: "claim_review",
        objective: "Review the bounded Claim context without making a decision.",
        scope,
        workspace_revision: "sha256:" + "2".repeat(64),
        target_claim_ref: "claim_probe_001",
        claims: [{ claim_id: "claim_probe_001", parent_claim_id: null, kind: "reaction_path/1", statement: "Probe claim.", status: "proposed", required_gates: [] }],
        gate_results: [],
        evidence: [],
        nodes: [{ node_id: "n000", parent_node: null, objective: "Probe", state: "closed", tags: [], result: null }],
        artifact_excerpts: [],
        basis_allowlist: ["claim_probe_001"],
      };
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: "agent_review_001",
        role: "review",
        authority: "advisory",
        operation: "claim_review",
        objective: "Review the bounded Claim context without making a decision.",
        workspace: {
          root: ctx.cwd,
          report_id: scope.report_id,
          revision: "sha256:" + "2".repeat(64),
        },
        scope,
        inputs: {
          evidence_snapshot: bindAgentDocument(
            "evidence-snapshot.json", "ts-review-evidence-snapshot/2", evidenceSnapshot,
          ),
          provider_input: bindAgentDocument(
            "provider-input.json", "ts-review-provider-input/2", providerInput,
          ),
        },
        capabilities: [],
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
          evidenceSnapshot,
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
