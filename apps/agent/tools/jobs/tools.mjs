import { TOOL_CONTRACTS, toolResult } from "../shared.mjs";
import { boundWorkspaceRoot } from "../context.mjs";
import { withJobQueryRecovery } from "./query-recovery.mjs";

export function createJobTools({ commandBridge, getTaskBinding = async () => null }) {
  return [
    ["jobStart", "start"], ["jobStatus", "status"], ["jobCollect", "collect"],
    ["jobCancel", "cancel"], ["jobProbe", "probe"], ["jobReconcile", "reconcile"],
  ].map(([key, operation]) => ({
    ...TOOL_CONTRACTS[key],
    async execute(params, api, context) {
      context?.abortSignal.throwIfAborted();
      const toolContext = api.coragent;
      const root = boundWorkspaceRoot(params, toolContext);
      const { root: _root, ...request } = params;
      const taskBinding = operation === "start" ? await getTaskBinding(context) : null;
      const invoke = () => commandBridge.execute_command(`job.${operation}`, operation === "start" ? {
        ...request,
        ...(!params.prepared_ref && !params.request_file ? { request_id: params.request_id || `${toolContext.operation_id}:${api.callId}` } : {}),
        session_id: toolContext.session_id,
        ...(taskBinding === null ? {} : { user_task_id: taskBinding.user_task_id }),
      } : request);
      const result = await (["status", "collect", "reconcile"].includes(operation)
        ? withJobQueryRecovery(root, `job_${operation}`, params, invoke) : invoke());
      return toolResult(result);
    },
  }));
}
