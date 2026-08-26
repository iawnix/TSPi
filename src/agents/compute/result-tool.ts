import { type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Compile } from "typebox/compile";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { buildComputeResult } = require("./output-schema.cjs");
const { COMPUTE_RESULT_TOOL_NAME } = require("./task-packet.cjs");

type ComputeResult = Record<string, unknown>;
type ActionLog = { tool: string; result: Record<string, unknown> }[];

export interface ComputeResultCapture {
  accepted: ComputeResult | null;
  attemptCount: number;
}

export function createComputeResultCapture(): ComputeResultCapture {
  return { accepted: null, attemptCount: 0 };
}

export function createComputeResultTool(
  packet: Record<string, unknown>,
  actions: ActionLog,
  capture: ComputeResultCapture,
): ToolDefinition {
  const parameters = createComputeResultSchema();
  const strictValidator = Compile(parameters);
  return {
    name: COMPUTE_RESULT_TOOL_NAME,
    label: "TS Compute Result",
    description: "Submit the bounded operational summary after the fixed Compute action plan reaches a terminal point.",
    parameters,
    executionMode: "sequential",
    prepareArguments(args) {
      if (!strictValidator.Check(args)) {
        const errors = strictValidator.Errors(args)
          .slice(0, 8)
          .map((error) => `${error.instancePath || "root"}: ${error.message}`)
          .join("; ");
        throw new Error(`ts_compute_result raw arguments violate the Compute schema: ${errors || "invalid arguments"}`);
      }
      return args as never;
    },
    async execute(_toolCallId, params) {
      if (capture.attemptCount > 2 || capture.accepted) {
        throw new Error("ts_compute_result accepts exactly one valid call");
      }
      const result = buildComputeResult(params, packet, actions) as ComputeResult;
      capture.accepted = result;
      return {
        content: [{ type: "text", text: "Compute result accepted." }],
        details: { accepted: true },
        terminate: true,
      };
    },
  };
}

export function createComputeResultSchema() {
  return Type.Object({
    summary: Type.String({ minLength: 1, maxLength: 2000 }),
    limitations: Type.Array(Type.String({ minLength: 1, maxLength: 1000 }), { maxItems: 8 }),
  }, { additionalProperties: false });
}

export { COMPUTE_RESULT_TOOL_NAME };
