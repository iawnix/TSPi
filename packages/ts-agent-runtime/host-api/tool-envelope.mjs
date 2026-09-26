import { validateHarnessToolDefinition } from "./tools.mjs";
import { validateToolInvocationContext } from "./workspace-context.mjs";

const RESULT_SCHEMA = "tspi-tool-result/1";
const ERROR_SCHEMA = "tspi-tool-error/1";
const FAILURE_CLASSES = Object.freeze([
  "validation", "authorization", "workspace", "conflict", "ambiguous", "transient", "execution", "contract",
]);

function classifyToolFailure(error) {
  const source = error && typeof error === "object" ? error : {};
  const explicit = typeof source.failure_class === "string" ? source.failure_class : "";
  if (FAILURE_CLASSES.includes(explicit)) return explicit;
  const text = `${source.code || ""} ${source.name || ""} ${source.message || error || ""}`.toLowerCase();
  if (/contract|metadata|envelope|schema/.test(text)) return "contract";
  if (/authoriz|permission|forbidden|policy/.test(text)) return "authorization";
  if (/workspace|session|root|symlink/.test(text)) return "workspace";
  if (/conflict|duplicate|already exists|idempot/.test(text)) return "conflict";
  if (/ambiguous|unknown outcome|uncertain/.test(text)) return "ambiguous";
  if (/timeout|timed out|temporar|unavailable|busy|rate limit|network|disconnect/.test(text)) return "transient";
  if (/invalid|required|argument|validation|parse/.test(text) || source.name === "TypeError") return "validation";
  return "execution";
}

function retryableToolFailure(error, failureClass) {
  if (["ambiguous", "contract", "authorization", "validation", "workspace", "conflict"].includes(failureClass)) {
    return false;
  }
  if (error && typeof error === "object" && error.retry_safe === true) return true;
  return failureClass === "transient";
}

function assertToolResult(response, toolName) {
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    const error = new TypeError(`${toolName} returned an invalid tool result envelope`);
    error.code = "tool_contract_violation";
    error.failure_class = "contract";
    throw error;
  }
  if (!Array.isArray(response.content) || response.content.some((item) => (
    !item || typeof item !== "object" || Array.isArray(item) || (item.type !== "text" && item.type !== "image")
  ))) {
    const error = new TypeError(`${toolName} returned invalid tool result content`);
    error.code = "tool_contract_violation";
    error.failure_class = "contract";
    throw error;
  }
  return response;
}

export function withToolResultEnvelope(response, toolName, toolCallId) {
  assertToolResult(response, toolName);
  const details = response.details && typeof response.details === "object" && !Array.isArray(response.details)
    ? response.details
    : {};
  if (details.envelope?.schema_version === RESULT_SCHEMA) return response;
  const result = details.result;
  return {
    ...response,
    details: {
      ...details,
      envelope: {
        schema_version: RESULT_SCHEMA,
        ok: true,
        tool: toolName,
        tool_call_id: typeof toolCallId === "string" && toolCallId ? toolCallId : null,
        result_schema: result && typeof result.schema_version === "string" ? result.schema_version : null,
      },
    },
  };
}

export function attachToolErrorEnvelope(error, toolName, toolCallId) {
  const source = error instanceof Error ? error : new Error(String(error));
  const failureClass = classifyToolFailure(source);
  if (!source.toolEnvelope) {
    source.toolEnvelope = {
      schema_version: ERROR_SCHEMA,
      ok: false,
      tool: toolName,
      tool_call_id: typeof toolCallId === "string" && toolCallId ? toolCallId : null,
      error: {
        code: typeof source.code === "string" && source.code ? source.code : "tool_error",
        message: source.message,
        retryable: retryableToolFailure(source, failureClass),
        failure_class: failureClass,
      },
    };
  }
  return source;
}

/**
 * Convert a tool failure into a normal AgentToolResult while retaining the
 * typed error. Pi Agent Core deliberately serializes thrown errors to text;
 * transport adapters use this result form before their post-tool hook marks
 * the call as isError.
 */
export function toolErrorResult(error, toolName, toolCallId) {
  const source = attachToolErrorEnvelope(error, toolName, toolCallId);
  return {
    content: [{ type: "text", text: source.message }],
    details: { envelope: source.toolEnvelope },
  };
}

export function wrapToolWithEnvelope(tool) {
  if (!tool || typeof tool.execute !== "function") throw new TypeError("tool envelope requires an executable tool");
  return {
    ...tool,
    async execute(toolCallId, ...args) {
      try {
        const response = await tool.execute(toolCallId, ...args);
        return withToolResultEnvelope(response, tool.name, toolCallId);
      } catch (error) {
        throw attachToolErrorEnvelope(error, tool.name, toolCallId);
      }
    },
  };
}

/** Wrap a production Harness tool without losing its structured error result. */
export function wrapToolForHarness(tool) {
  if (!tool || typeof tool.execute !== "function") throw new TypeError("tool envelope requires an executable tool");
  if (tool.metadata !== undefined) {
    validateHarnessToolDefinition(tool, { source: "Harness tool", requireCanonical: true });
  }
  const wrapped = wrapToolWithEnvelope(tool);
  const enforceInvocationContext = tool.metadata !== undefined;
  return {
    ...wrapped,
    async execute(toolCallId, ...args) {
      try {
        let executionArgs = args;
        if (enforceInvocationContext) {
          // Harness-native tools receive (params, onUpdate, toolContext,
          // invocation, context). Bind and validate the trusted context before
          // any implementation code or external side effect can run.
          const [params, onUpdate, toolContext, invocation, context] = args;
          const boundContext = validateToolInvocationContext(tool, toolContext, invocation, toolCallId);
          executionArgs = [params, onUpdate, boundContext, invocation, context];
        }
        return await wrapped.execute(toolCallId, ...executionArgs);
      } catch (error) {
        return toolErrorResult(error, tool.name, toolCallId);
      }
    },
  };
}

function toolResultText(content) {
  if (!Array.isArray(content)) return "tool execution failed";
  const text = content
    .filter((item) => item && item.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join("\n")
    .trim();
  return text || "tool execution failed";
}

function isRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

/**
 * Post-tool hook: preserve an existing envelope and set isError, or create a
 * minimal envelope for failures that occurred before the tool wrapper ran
 * (for example argument validation or a before-tool policy block).
 */
export function markToolEnvelopeError(event) {
  if (event?.details?.envelope?.schema_version === ERROR_SCHEMA) return { isError: true };
  if (event?.isError !== true) return undefined;
  const details = isRecord(event.details) ? event.details : {};
  if (event?.recovery === true && event?.replay === "never") {
    return {
      details: {
        ...details,
        envelope: {
          schema_version: ERROR_SCHEMA,
          ok: false,
          tool: typeof event.toolName === "string" ? event.toolName : null,
          tool_call_id: typeof event.toolCallId === "string" && event.toolCallId ? event.toolCallId : null,
          error: {
            code: "tool_replay_forbidden",
            message: `Tool ${event.toolName || "unknown"} cannot be replayed during recovery`,
            retryable: false,
            failure_class: "authorization",
          },
        },
      },
      isError: true,
    };
  }
  const failureClass = classifyToolFailure({ message: toolResultText(event.content), name: "ToolError" });
  return {
    details: {
      ...details,
      envelope: {
        schema_version: ERROR_SCHEMA,
        ok: false,
        tool: typeof event.toolName === "string" ? event.toolName : null,
        tool_call_id: typeof event.toolCallId === "string" && event.toolCallId ? event.toolCallId : null,
        error: {
          code: "tool_error",
          message: toolResultText(event.content),
          retryable: failureClass === "transient",
          failure_class: failureClass,
        },
      },
    },
    isError: true,
  };
}

export const TOOL_RESULT_SCHEMA_VERSION = RESULT_SCHEMA;
export const TOOL_ERROR_SCHEMA_VERSION = ERROR_SCHEMA;
