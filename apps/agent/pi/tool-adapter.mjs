/** Adapt Pi's local coding tools to Durable without changing their search semantics. */
export function adaptCodingTool(tool) {
  return {
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
    prepareArguments: tool.prepareArguments,
    replay: "safe",
    executionMode: "sequential",
    async execute(args, api, context) {
      context.abortSignal?.throwIfAborted();
      // Pi's grep/find/ls return bounded final output and do not emit updates.
      // Preserve their content, details and errors unchanged for Durable.
      return tool.execute(api.callId, args, context.abortSignal);
    },
  };
}
