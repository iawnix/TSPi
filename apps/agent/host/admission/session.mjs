/** Session mutations execute on the pinned Pi transaction boundary. */
export const SESSION_ADMISSION_SERVICE_ID = "coragent.session-admission";

export function createSessionAdmission({ harness, conversation, LiveDoc }) {
  return {
    async interrupt({ turnId }, context) {
      if (typeof turnId !== "string" || !turnId) throw new Error("turn_id is required");
      const result = await conversation.commit(async tx => {
        const live = await tx.doc(LiveDoc, conversation.id);
        if (!live.run || String(live.run.inputs[0]) !== turnId) {
          return { accepted: false, operation_id: turnId, error: { code: "turn_not_active", message: "The requested turn is no longer active" } };
        }
        const task = await tx.task(live.run.taskId);
        if (!task || task.state.status === "terminal") {
          return { accepted: false, operation_id: turnId, error: { code: "turn_not_active", message: "The requested turn has already ended" } };
        }
        if (!task.abortRequested) tx.setTask({ ...task, abortRequested: true });
        return { accepted: true, operation_id: turnId };
      }, context);
      if (result.accepted) harness.resume();
      return result;
    },
  };
}
