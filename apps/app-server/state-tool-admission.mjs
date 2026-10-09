/** Current State owns admission. Only local diagnostics survive bridge failure. */
export async function admitStateTool({ call, metadata, lifecycle, readLiveness, stateArguments, runId }) {
  if (!metadata) return { block: `No lifecycle metadata for ${call.name}` };
  let args;
  try { args = await stateArguments(); }
  catch (error) {
    return { block: JSON.stringify({ schema_version: "tspi-lifecycle-admission-error/1",
      code: "research_tool_arguments_invalid", reason: String(error?.message || error), tool_name: call.name }) };
  }
  try {
    const liveness = await readLiveness({ tool: { name: call.name,
      args, effect: metadata.effect, phase: metadata.phase } });
    if (typeof liveness?.tool_admission?.accepted !== "boolean") throw new Error("Research State returned no authoritative tool admission");
    lifecycle.setDurableLiveness(liveness);
  } catch (error) {
    // job_status persists observations; bash and apparent query scripts can write.
    // Never admit them using a cached readiness decision.
    if (["read", "system_prompt"].includes(call.name) && metadata.effect === "read") return { arguments: call.arguments };
    return { block: JSON.stringify({ schema_version: "tspi-lifecycle-admission-error/1",
      code: "research_liveness_unavailable", reason: String(error?.message || error), tool_name: call.name }) };
  }
  const admission = lifecycle.admitTool({ runId, toolName: call.name, toolCallId: call.id, args: call.arguments });
  return admission.accepted ? { arguments: args } : { block: JSON.stringify({
    schema_version: "tspi-lifecycle-admission-error/1", code: admission.code || "tool_phase_transition_denied",
    reason: admission.reason, tool_name: call.name }) };
}

/** Preserve a diagnostic final answer when State cannot be read. No checkpoint
 * or continuation is inferred from an unavailable authority. */
export async function finishStateYield({ checkpoint, prune, onError = () => {} }) {
  let follow;
  try {
    follow = await checkpoint();
  } catch (error) {
    onError(error);
    return undefined;
  }
  try { await prune?.(); } catch (error) { onError(error); }
  return follow?.followUp ? { continue: follow.followUp } : undefined;
}
