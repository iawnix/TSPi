import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { runArtifactOperator } from "../src/agents/artifacts/runtime.ts";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-report-child", {
    description: "Run one recording-provider report child session.",
    handler: async (_args, ctx) => {
      const actions: { tool: string; result: Record<string, unknown> }[] = [];
      const packageRef = "reports/recording-report";
      const canonical = {
        operation: "build",
        state: "built",
        package_ref: packageRef,
        report_ref: `${packageRef}/final_report.md`,
        context_ref: `${packageRef}/report_context.json`,
        email_summary_ref: `${packageRef}/email_summary.md`,
        assets_ref: `${packageRef}/assets`,
        manifest_ref: `${packageRef}/package_manifest.json`,
        manifest_digest: "sha256:" + "5".repeat(64),
        workspace_revision: "sha256:" + "6".repeat(64),
        artifact_refs: [
          `${packageRef}/final_report.md`,
          `${packageRef}/report_context.json`,
          `${packageRef}/email_summary.md`,
          `${packageRef}/assets`,
          `${packageRef}/package_manifest.json`,
        ],
      };
      const tool: ToolDefinition = {
        name: "ts_workspace_report_build",
        label: "TS Recording Report Build",
        description: "Return the pre-bound recording report result exactly once.",
        parameters: { type: "object", properties: {}, additionalProperties: false } as never,
        async execute() {
          if (actions.length) throw new Error("recording report tool may be called only once");
          actions.push({ tool: "ts_workspace_report_build", result: canonical });
          return {
            content: [{ type: "text", text: JSON.stringify(canonical) }],
            details: { result: canonical },
          };
        },
      };
      const scope = {
        report_id: "rep_report_001",
        node_ids: [],
        hypothesis_id: null,
        pathway_id: null,
      };
      const packet = {
        schema_version: "ts-agent-task/2",
        task_id: "agent_report_001",
        role: "report",
        authority: "operational",
        operation: "build",
        objective: "Execute the bound recording report build.",
        workspace: {
          root: ctx.cwd,
          report_id: scope.report_id,
          revision: canonical.workspace_revision,
        },
        scope,
        inputs: {
          package_ref: packageRef,
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
        const result = await runArtifactOperator({
          workspaceRoot: ctx.cwd,
          packet,
          role: "report",
          tools: [tool],
          actions,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_REPORT:${JSON.stringify(result)}`, "info");
      } catch (error) {
        ctx.ui.notify(`TS_TEST_REPORT_ERROR:${error instanceof Error ? error.message : String(error)}`, "error");
      }
    },
  });
}
