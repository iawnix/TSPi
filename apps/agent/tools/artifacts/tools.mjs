import { TOOL_CONTRACTS, toolResult } from "../shared.mjs";
import { boundWorkspaceRoot } from "../context.mjs";

export function createArtifactTools({ commandBridge }) {
  return [["artifactRegister", "register"], ["artifactCreate", "create"], ["artifactRead", "read"]]
    .map(([key, operation]) => ({
      ...TOOL_CONTRACTS[key],
      async execute(params, api, context) {
        context?.abortSignal.throwIfAborted();
        boundWorkspaceRoot(params, api.coragent);
        const { root: _root, ...request } = params;
        return toolResult(await commandBridge.execute_command(`artifact.${operation}`, request));
      },
    }));
}
