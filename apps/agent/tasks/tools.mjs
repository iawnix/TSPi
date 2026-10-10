import { TOOL_CONTRACTS, toolResult } from "../tools/shared.mjs";

export function createTaskTools(getController) {
  return [["taskBegin", "begin"], ["taskRead", "current"], ["taskUpdate", "update"]].map(([key, method]) => ({
    ...TOOL_CONTRACTS[key],
    async execute(params, api, context) {
      context.abortSignal?.throwIfAborted();
      const controller = getController();
      const result = method === "current" ? await controller.current(context)
        : await controller[method](params, `tool:${api.taskId}`, context);
      return toolResult(result);
    },
  }));
}
