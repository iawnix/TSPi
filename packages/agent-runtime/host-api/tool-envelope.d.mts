export const TOOL_RESULT_SCHEMA_VERSION: "tspi-tool-result/1";
export const TOOL_ERROR_SCHEMA_VERSION: "tspi-tool-error/1";

export function withToolResultEnvelope(
  response: any,
  toolName: string,
  toolCallId?: string,
): any;

export function attachToolErrorEnvelope(
  error: unknown,
  toolName: string,
  toolCallId?: string,
): Error & { toolEnvelope?: any };

export function toolErrorResult(
  error: unknown,
  toolName: string,
  toolCallId?: string,
): any;

export function wrapToolWithEnvelope(tool: any): any;
export function wrapToolForHarness(tool: any): any;
export function markToolEnvelopeError(event: any): { details: any; isError: true } | { isError: true } | undefined;
