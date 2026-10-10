import { recordJobLookup } from "../jobs/query-recovery.mjs";
import { TOOL_CONTRACTS, toolResult } from "../shared.mjs";
import { createCommandService } from "../commands.mjs";
import { boundWorkspaceRoot } from "../context.mjs";
import { RESEARCH_MEMORY_WRITE_PRINCIPAL } from "../../bridge/ports.mjs";

const RESEARCH_OUTPUT_LIMITS = Object.freeze({ maxBytes: 50 * 1024, maxLines: 2000, retain: "head" });

export function createResearchTools({ commandBridge }) {
  const commands = createCommandService({ execute: ({ command, params, signal }) => {
    signal?.throwIfAborted();
    return commandBridge.execute_command(command, params);
  } });
  return [["state", "read"], ["search", "search"], ["create", "create"], ["update", "update"], ["result", "result"]].map(([key, operation]) => ({
    ...TOOL_CONTRACTS[key],
    outputLimits: RESEARCH_OUTPUT_LIMITS,
    async execute(params, api, context) {
      const root = boundWorkspaceRoot(params, api.coragent);
      const {root: _root, ...request} = params;
      const writing = ["create", "update", "result"].includes(operation);
      if (operation !== "search") request.session_id = api.coragent?.session_id;
      if (writing) {
        requireNativeWrites(`research_${operation}`, api.coragent);
        request.request_id = `${api.coragent?.session_id}:${api.callId}`;
      }
      const result = await commands.execute(`research.${operation}`, root, request, context?.abortSignal);
      const visible = researchToolView(result, operation, params);
      if (visible.complete && result?.read_basis) await commands.execute("research.observe", root, { session_id: request.session_id, read_basis: result.read_basis }, context?.abortSignal);
      if (!writing) recordJobLookup(root);
      return toolResult(visible.value, visible.text);
    },
  }));
}

// Pi bounds explicit tool text after execute. Compact JSON avoids line-limit
// truncation; oversized replies keep commit outcomes and offer smaller reads.
// Their omitted Node fields must never advance the session's read receipt.
function researchToolView(result, operation, params) {
  const text = JSON.stringify(result);
  if (Buffer.byteLength(text) <= RESEARCH_OUTPUT_LIMITS.maxBytes) return {value: result, text, complete: true};
  const read = [];
  if (operation === "read" || operation === "search") {
    read.push({tool: `research_${operation}`, ...params, limit: Math.max(1, Math.min(operation === "search" ? 5 : 2000, Math.floor((params.limit || 16000) / 2)))});
  } else {
    for (const ref of new Set([result.node?.id, result.result?.id, result.ref].filter(Boolean))) {
      read.push({tool: "research_read", ref, limit: 2000});
    }
  }
  const value = {content_omitted: true,
    message: "The response exceeds the tool output budget. Read the listed references in smaller pages. For a large Node, select one field, for example field=proposal. Omitted Node fields have not been acknowledged as read.",
    ...Object.fromEntries(["schema_version", "accepted", "result_saved", "assessment_selected", "conflict", "ref"].filter(key => key in result).map(key => [key, result[key]])),
    ...(result.node ? {node: {id: result.node.id, revision: result.node.revision}} : {}),
    ...(result.result ? {result: {id: result.result.id, node_id: result.result.node_id}} : {}), read};
  return {value, text: JSON.stringify(value), complete: false};
}


function requireNativeWrites(toolName, toolContext) {
  // Every write requires the Host-bound Root Agent principal.
  if (toolContext?.principal !== RESEARCH_MEMORY_WRITE_PRINCIPAL) {
    throw new Error(`${toolName} requires the Root Agent principal`);
  }
}
