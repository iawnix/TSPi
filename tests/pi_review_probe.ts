import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runScientificReview } from "../src/agents/review/runtime.ts";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-review-child", {
    description: "Run one tool-free recording-provider review child session.",
    handler: async (_args, ctx) => {
      const scope = {
        report_id: "rep_review_001",
        node_ids: ["n000"],
        hypothesis_id: null,
        pathway_id: null,
      };
      const packet = {
        schema_version: "ts-agent-task/1",
        task_id: "agent_review_001",
        role: "review",
        authority: "advisory",
        operation: "mechanism",
        objective: "Review the bounded mechanism context without making a decision.",
        workspace: {
          root: ctx.cwd,
          report_id: scope.report_id,
          revision: "sha256:" + "2".repeat(64),
        },
        scope,
        inputs: {
          context: { workspace: "Recording-provider workspace", node: null, backtrack: null },
          evidence: [],
          artifact_excerpts: [],
          basis_allowlist: [],
          evidence_ceiling: ["mechanism"],
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
