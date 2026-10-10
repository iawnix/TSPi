import { parseSlashCommand, COMMAND_DEFINITIONS } from "../../tools/commands.mjs";

// A non-local Chord service: callers always reach the attached worker, including
// over SSH. The worker supplies the identity and the already-bound kernel bridge.
export const CLIENT_QUERIES_SERVICE_ID = "coragent.client-queries";

export function createClientQueries({ workspaceId, sessionId, commandBridge, promptManifest, readTelemetry }) {
  const envelope = (result) => ({ workspace_id: workspaceId, session_id: sessionId, result });
  return {
    async telemetry(context) {
      context?.abortSignal?.throwIfAborted();
      return envelope(await readTelemetry(context));
    },
    async research(input, context) {
      context?.abortSignal?.throwIfAborted();
      try {
        if (typeof input !== "string") throw new TypeError("research arguments must be text");
        const invocation = parseSlashCommand("research", input);
        if (COMMAND_DEFINITIONS[invocation.command]?.effect !== "read") throw new Error("Terminal research queries must be read-only");
        const result = await commandBridge.execute_command(invocation.command, invocation.params);
        context?.abortSignal?.throwIfAborted();
        return envelope(result);
      } catch (error) {
        // Pi deliberately masks arbitrary remote exceptions. Preserve useful
        // command errors as data instead of reporting "Internal server error".
        return { ...envelope(null), error: { code: error.code || error.name, message: error.message } };
      }
    },
    async systemPrompt(context) {
      context?.abortSignal?.throwIfAborted();
      return envelope(promptManifest);
    },
  };
}
