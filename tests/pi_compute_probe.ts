import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { runComputeOperator } from "../src/agents/compute/runtime.ts";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-compute-child", {
    description: "Run one single-tool recording-provider compute child session.",
    handler: async (_args, ctx) => {
      const intentId = "intent_recording_001";
      const intentDigest = "sha256:" + "3".repeat(64);
      const artifactRef = `nodes/n000/attempts/${intentId}/prepared.json`;
      const actions: { tool: string; result: Record<string, unknown> }[] = [];
      const canonical = {
        action_status: "completed",
        operation: "prepare",
        state: "prepared",
        program_status: "not_run",
        error_class: null,
        exit_status: null,
        intent_id: intentId,
        node_id: "n000",
        artifact_refs: [artifactRef],
        provenance: { backend: "gaussian", intent_digest: intentDigest },
      };
      const tool: ToolDefinition = {
        name: "ts_workspace_compute_prepare",
        label: "TS Recording Compute Prepare",
        description: "Return the pre-bound recording preparation result exactly once.",
        parameters: { type: "object", properties: {}, additionalProperties: false } as never,
        async execute() {
          if (actions.length) throw new Error("recording compute tool may be called only once");
          actions.push({ tool: "ts_workspace_compute_prepare", result: canonical });
          return {
            content: [{ type: "text", text: JSON.stringify(canonical) }],
            details: { result: canonical },
          };
        },
      };
      const scope = {
        report_id: "rep_compute_001",
        node_ids: ["n000"],
        hypothesis_id: null,
        pathway_id: null,
      };
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: "agent_compute_001",
        role: "backend",
        authority: "operational",
        operation: "prepare",
        objective: "Execute the bound recording compute preparation.",
        workspace: {
          root: ctx.cwd,
          report_id: scope.report_id,
          revision: "sha256:" + "4".repeat(64),
        },
        scope,
        inputs: {
          intent_id: intentId,
          intent_ref: `nodes/n000/attempts/${intentId}/intent.json`,
          intent_digest: intentDigest,
          node_id: "n000",
          backend: "gaussian",
          basis_allowlist: [],
        },
        capabilities: [tool.name],
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
        const result = await runComputeOperator({
          workspaceRoot: ctx.cwd,
          packet,
          backend: "gaussian",
          tools: [tool],
          actions,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_COMPUTE:${JSON.stringify(result)}`, "info");
      } catch (error) {
        ctx.ui.notify(`TS_TEST_COMPUTE_ERROR:${error instanceof Error ? error.message : String(error)}`, "error");
      }
    },
  });
}
