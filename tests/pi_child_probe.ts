import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { runArtifactOperator } from "../src/agents/artifacts/runtime.ts";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-child", {
    description: "Run one recording-provider child session for integration testing.",
    handler: async (_args, ctx) => {
      const actions: { tool: string; result: Record<string, unknown> }[] = [];
      const canonical = {
        operation: "render",
        state: "rendered",
        node_id: "n000",
        output_ref: "nodes/n000/outputs/recording.png",
        artifact_refs: ["nodes/n000/outputs/recording.png"],
      };
      const tool: ToolDefinition = {
        name: "ts_workspace_render_execute",
        label: "TS Recording Render",
        description: "Return the pre-bound recording result exactly once.",
        parameters: { type: "object", properties: {}, additionalProperties: false } as never,
        async execute() {
          if (actions.length) throw new Error("recording tool may be called only once");
          actions.push({ tool: "ts_workspace_render_execute", result: canonical });
          return {
            content: [{ type: "text", text: JSON.stringify(canonical) }],
            details: { result: canonical },
          };
        },
      };
      const scope = {
        report_id: "rep_recording_001",
        node_ids: ["n000"],
        hypothesis_id: null,
        pathway_id: null,
      };
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: "agent_recording_001",
        role: "render",
        authority: "operational",
        operation: "render",
        objective: "Execute the bound recording render.",
        workspace: {
          root: ctx.cwd,
          report_id: scope.report_id,
          revision: "sha256:" + "1".repeat(64),
        },
        scope,
        inputs: {
          node_id: "n000",
          input_refs: ["inputs/reactant.xyz"],
          output_ref: canonical.output_ref,
          basis_allowlist: ["inputs/reactant.xyz"],
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
        const result = await runArtifactOperator({
          workspaceRoot: ctx.cwd,
          packet,
          role: "render",
          tools: [tool],
          actions,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_CHILD:${JSON.stringify(result)}`, "info");
      } catch (error) {
        ctx.ui.notify(`TS_TEST_CHILD_ERROR:${error instanceof Error ? error.message : String(error)}`, "error");
      }
    },
  });
}
