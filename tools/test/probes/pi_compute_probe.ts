import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { createRequire } from "node:module";
import { runComputeOperator } from "../../../packages/ts-agent-runtime/agents/compute/runtime.ts";

const require = createRequire(import.meta.url);
const { buildComputeTask, COMPUTE_ACTION_TOOL_NAMES } = require("../../../packages/ts-agent-runtime/agents/compute/task-packet.cjs");

type ActionLog = { tool: string; result: Record<string, unknown> }[];

export default function (pi: ExtensionAPI) {
  pi.registerCommand("ts-test-compute-child", {
    description: "Run one recording-provider Compute child session.",
    handler: async (args, ctx) => {
      const scenario = String(args || "launch").trim() || "launch";
      const operation = operationForScenario(scenario);
      const intentDigest = `sha256:${"2".repeat(64)}`;
      const binding = {
        intentId: "calc_1",
        intentDigest,
        executionKind: "remote",
        capabilityDescriptorDigest: `sha256:${"3".repeat(64)}`,
      };
      const task = buildComputeTask({
        runId: "sub_1",
        workspaceRoot: ctx.cwd,
        operation,
        capability: "gaussian.opt_freq",
        capabilityVersion: "1",
        capabilityDescriptor: {
          capability: "gaussian.opt_freq",
          version: "1",
          input_roles: ["gjf"],
          output_roles: ["program_output", "optimized_geometry", "frequencies"],
          parsers: ["gaussian.output/2"],
        },
        nodeId: "node_1",
        binding,
        tailArtifact: operation === "inspect" ? "gaussian.out" : undefined,
        tailLines: operation === "inspect" ? 80 : undefined,
        artifacts: operation === "finalize" ? ["gaussian.out"] : undefined,
        artifactRef: operation === "finalize"
          ? "nodes/node_1/attempts/calc_1/outputs/remote/gaussian.out"
          : undefined,
      });
      const actions: ActionLog = [];
      const tools = toolsForScenario(scenario, intentDigest, actions);
      try {
        const result = await runComputeOperator({
          workspaceRoot: ctx.cwd,
          packet: task,
          tools,
          actions,
          parentModel: { provider: "ts-recording", id: "recording-model" } as never,
          parentApiKey: "recording-key",
          thinkingLevel: "off",
          timeoutMs: 10_000,
          signal: ctx.signal,
        });
        ctx.ui.notify(`TS_TEST_COMPUTE:${JSON.stringify(result)}`, "info");
      } catch (error) {
        const value = error && typeof error === "object" ? error as Record<string, unknown> : {};
        ctx.ui.notify(`TS_TEST_COMPUTE_ERROR:${JSON.stringify({
          message: error instanceof Error ? error.message : String(error),
          actions: Array.isArray(value.computeActions) ? value.computeActions : actions,
        })}`, "error");
      }
    },
  });
}

function toolsForScenario(scenario: string, intentDigest: string, actions: ActionLog): ToolDefinition[] {
  const operation = operationForScenario(scenario);
  const names = operation === "launch"
    ? [COMPUTE_ACTION_TOOL_NAMES.prepare, COMPUTE_ACTION_TOOL_NAMES.submit]
    : operation === "inspect"
      ? [COMPUTE_ACTION_TOOL_NAMES.status, COMPUTE_ACTION_TOOL_NAMES.tail]
      : operation === "finalize"
        ? [COMPUTE_ACTION_TOOL_NAMES.collect, COMPUTE_ACTION_TOOL_NAMES.parse]
        : [COMPUTE_ACTION_TOOL_NAMES.cancel];
  return names.map((name: string) => ({
    name,
    label: name,
    description: `Execute the bound ${name} probe action exactly once.`,
    executionMode: "sequential",
    parameters: Type.Object({}, { additionalProperties: false }),
    async execute() {
      if (actions.some((action) => action.tool === name)) throw new Error(`${name} was replayed`);
      const result = resultFor(name, scenario, intentDigest);
      const actionStatus = actionStatusFor(name, scenario);
      actions.push({ tool: name, result: { action_status: actionStatus, result } });
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: { result },
      };
    },
  }));
}

function resultFor(name: string, scenario: string, intentDigest: string): Record<string, unknown> {
  const action = Object.entries(COMPUTE_ACTION_TOOL_NAMES).find(([, tool]) => tool === name)?.[0] || "action";
  const ambiguous = scenario.includes("ambiguous") && ["submit", "cancel"].includes(action);
  const state = ambiguous
    ? "unknown"
    : {
        prepare: "prepared",
        submit: "submitted",
        status: "running",
        tail: "tail_returned",
        collect: "collected",
        parse: "parsed",
        cancel: "cancelled",
      }[action] || "completed";
  return {
    schema_version: action === "tail" ? "ts-calculation-tail/1" : "ts-calculation-result/2",
    intent_id: "calc_1",
    node_id: "node_1",
    capability: "gaussian.opt_freq",
    capability_version: "1",
    expected_output_roles: ["program_output", "optimized_geometry", "frequencies"],
    state,
    program_status: action === "parse" ? "completed" : action === "status" ? "running" : "not_run",
    error_class: ambiguous ? (action === "submit" ? "submission_ambiguous" : "cancellation_ambiguous") : null,
    exit_status: action === "parse" ? 0 : null,
    artifact_refs: ["collect", "parse"].includes(action)
      ? ["nodes/node_1/attempts/calc_1/outputs/remote/gaussian.out"]
      : [],
    control: ["submit", "cancel"].includes(action)
      ? {
          effect_outcome: ambiguous ? "unknown" : "succeeded",
          retry_disposition: ambiguous ? "reconcile_only" : "known_success",
          reconciliation_required: ambiguous,
        }
      : undefined,
    provenance: {
      intent_digest: intentDigest,
      capability: "gaussian.opt_freq",
      capability_version: "1",
      capability_descriptor_digest: `sha256:${"3".repeat(64)}`,
    },
  };
}

function actionStatusFor(name: string, scenario: string): "completed" | "unknown" {
  if (!scenario.includes("ambiguous")) return "completed";
  return [COMPUTE_ACTION_TOOL_NAMES.submit, COMPUTE_ACTION_TOOL_NAMES.cancel].includes(name)
    ? "unknown"
    : "completed";
}

function operationForScenario(value: string): "launch" | "inspect" | "finalize" | "cancel" {
  if (value.startsWith("launch")) return "launch";
  if (value.startsWith("inspect")) return "inspect";
  if (value.startsWith("finalize")) return "finalize";
  if (value.startsWith("cancel")) return "cancel";
  throw new Error(`unsupported Compute probe scenario: ${value}`);
}
