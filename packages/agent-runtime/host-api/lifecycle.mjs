/**
 * Transport-neutral helpers for the Research Turn boundary.
 *
 * The Research State remains the authority for lifecycle state. These functions only
 * reduce its bounded liveness read model into a Host/adapter follow-up.
 */

export const RESEARCH_LIFECYCLE_STATES = Object.freeze([
  "idle",
  "continue_required",
  "decision_needed",
  "user_input_required",
  "waiting_external",
  "deferred",
  "blocked",
  "terminal",
]);

/**
 * Descriptive phases for one domain-neutral Research Turn. `wake` identifies a
 * Monitor-triggered run. Research State owns admission for every tool.
 * Tool metadata continues to use the execution phases below.
 */
export const RESEARCH_TURN_PHASES = Object.freeze([
  "orient",
  "advance",
  "prepare",
  "execute",
  "interpret",
  "checkpoint",
  "wake",
]);

/**
 * Pi may add `isError` only after the after-tool hook chain has started. Native
 * adapters therefore also expose failures through the structured envelope.
 */
export function toolEventIsError(event) {
  if (event?.isError === true) return true;
  const envelope = event?.details?.envelope;
  return envelope?.schema_version === "tspi-tool-error/1" || envelope?.ok === false;
}

const DEFAULT_TOOL_PHASES = Object.freeze(["orient", "advance", "prepare", "execute", "interpret", "checkpoint"]);

/** Host tracks tool phases and serializes calls; State alone decides research readiness. */
export function createResearchLifecycleController({ metadata = {}, replayMode = "normal" } = {}) {
  const toolMetadata = metadata && typeof metadata === "object" ? metadata : {};
  const authorities = uniqueValues(Object.values(toolMetadata).map((value) => value?.authority));
  const effects = uniqueValues(Object.values(toolMetadata).map((value) => value?.effect));
  let state = {
    run_id: null,
    trigger: "agent.prompt",
    lifecycle_phase: "orient",
    replay_mode: replayMode,
    last_tool: null,
    phase_before_tool: null,
    active_tool_call_id: null,
  };
  let durableLiveness = null;

  function setDurableLiveness(value) {
    durableLiveness = value && typeof value === "object" ? structuredClone(value) : null;
    return snapshot();
  }

  function beginRun({ runId, messages = [], trigger, replay_mode: requestedReplayMode } = {}) {
    if (typeof runId !== "string" || !runId.trim()) throw new TypeError("lifecycle runId must be a non-empty identifier");
    const inferredTrigger = trigger || (isMonitorWake(messages) ? "monitor.wake" : "agent.prompt");
    const effectiveReplayMode = requestedReplayMode || replayMode;
    if (!["normal", "recovery", "reconcile"].includes(effectiveReplayMode)) {
      throw new TypeError(`unsupported lifecycle replay mode: ${effectiveReplayMode}`);
    }
    // Pi may call GenerationTask.beforeRequest more than once for the same
    // durable run (tool continuations, retries, and recovery all do this).
    // Reinitialising the phase here strands a valid checkpoint in `orient` and
    // makes every subsequent checkpoint admission fail. A run identity is the
    // lifecycle identity, so repeated initialisation must be idempotent.
    if (state.run_id === runId) return snapshot();
    state = {
      run_id: runId,
      trigger: inferredTrigger,
      lifecycle_phase: inferredTrigger === "monitor.wake" ? "wake" : "orient",
      replay_mode: effectiveReplayMode,
      last_tool: null,
      phase_before_tool: null,
      active_tool_call_id: null,
    };
    return snapshot();
  }

  function admitTool({ runId, toolName, toolCallId, args } = {}) {
    ensureRun(runId);
    const metadataForTool = toolMetadata[toolName];
    if (!metadataForTool) return { ...snapshot(), accepted: false, code: "tool_metadata_missing", reason: `No lifecycle metadata for ${toolName}` };
    // The Harness may execute a batch in parallel in other integrations. A
    // lifecycle phase is a single ordered lane, so never let a second
    // state-changing admission overwrite the first tool's rollback marker.
    // Sequential callers clear this marker in completeTool before admitting
    // the next call.
    if (state.active_tool_call_id !== null) {
      const sameCall = toolCallId && state.active_tool_call_id === toolCallId;
      if (!sameCall) {
        return {
          accepted: false,
          code: "lifecycle_tool_in_flight",
          reason: `lifecycle tool ${state.last_tool || "unknown"} is still in flight`,
          expected_phases: allowedToolPhases(state.lifecycle_phase),
          ...snapshot(),
        };
      }
      return { accepted: true, duplicate: true, ...snapshot() };
    }
    const operations = args?.operations || args?.changeSet?.operations || args?.change?.operations;
    const evidenceUpdate = toolName === "research_change" && Array.isArray(operations) && operations.length > 0
      && operations.every((operation) => ["create_finding", "register_artifact", "link_evidence", "transition_attempt"].includes(operation?.type));
    const targetPhase = evidenceUpdate ? "interpret" : metadataForTool.phase;
    if (durableLiveness?.tool_admission?.accepted === false) {
      return { ...snapshot(), ...durableLiveness.tool_admission };
    }
    state = {
      ...state,
      // Track the admitted tool's phase without creating a second workflow gate.
      lifecycle_phase: targetPhase,
      last_tool: toolName,
      phase_before_tool: state.lifecycle_phase,
      active_tool_call_id: typeof toolCallId === "string" && toolCallId ? toolCallId : "__implicit__",
    };
    return { accepted: true, ...snapshot() };
  }

  function completeTool({ runId, toolName, toolCallId, args, isError = false } = {}) {
    ensureRun(runId);
    // Ignore stale/out-of-order completions instead of applying their phase
    // transition to whichever tool is currently active. This is important
    // for Hosts that recover a batch or accidentally deliver callbacks out of
    // order; the lifecycle lane remains deterministic and retryable.
    if (state.active_tool_call_id !== null && (
      state.last_tool !== toolName
      || (typeof toolCallId === "string" && toolCallId && state.active_tool_call_id !== "__implicit__" && state.active_tool_call_id !== toolCallId)
    )) {
      return { ...snapshot(), ignored: true, code: "lifecycle_completion_mismatch" };
    }
    if (isError) {
      if (state.last_tool === toolName && state.phase_before_tool) {
        state = { ...state, lifecycle_phase: state.phase_before_tool, phase_before_tool: null, active_tool_call_id: null };
      }
      return snapshot();
    }
    const metadataForTool = toolMetadata[toolName];
    if (!metadataForTool) return snapshot();
    const phase = metadataForTool.phase;
    // Phase is an observation of tool activity, never a second research gate.
    const phaseBeforeTool = state.phase_before_tool || state.lifecycle_phase;
    const nextPhase = phase === "orient"
      ? (phaseBeforeTool === "orient" || phaseBeforeTool === "wake" || phaseBeforeTool === "checkpoint" ? "advance" : phaseBeforeTool)
      : phase;
    state = { ...state, lifecycle_phase: nextPhase, phase_before_tool: null, active_tool_call_id: null };
    return snapshot();
  }

  function contextPatch() {
    const allowedPhases = [...DEFAULT_TOOL_PHASES];
    return {
      operation_id: state.run_id,
      lifecycle_phase: state.lifecycle_phase,
      replay_mode: state.replay_mode,
      allowed_authorities: authorities.length ? authorities : ["host_read"],
      allowed_effects: effects.length ? effects : ["read"],
      allowed_phases: allowedPhases,
    };
  }

  function snapshot() {
    return Object.freeze({
      ...state,
      allowed_phases: Object.freeze(allowedToolPhases(state.lifecycle_phase)),
    });
  }

  function ensureRun(runId) {
    if (typeof runId !== "string" || !runId.trim()) throw new TypeError("lifecycle tool admission requires runId");
    if (state.run_id !== runId) beginRun({ runId });
  }

  return Object.freeze({ beginRun, admitTool, completeTool, contextPatch, setDurableLiveness, snapshot });
}

function allowedToolPhases() {
  // Phase labels are descriptive. Readiness and recovery come from State,
  // including independent work after evidence writes and interpretation.
  return [...DEFAULT_TOOL_PHASES];
}

function uniqueValues(values) {
  return [...new Set(values.filter((value) => typeof value === "string" && value))];
}

function isMonitorWake(messages) {
  const text = Array.isArray(messages)
    ? messages.map((message) => messageText(message)).join("\n")
    : messageText(messages);
  return text.includes("A compute monitor event requires attention.") || text.includes("source=monitor");
}


function messageText(message) {
  if (typeof message === "string") return message;
  if (!message || typeof message !== "object") return "";
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content)) return "";
  return message.content.map((part) => typeof part === "string" ? part : part?.text || "").join(" ");
}

/**
 * A checkpoint is successful when the Agent has either recorded a next
 * action, is waiting for an external Attempt, has explicitly held the scope,
 * or has closed it. Hosts must not turn an already-valid `continue_required`
 * state into an immediate same-turn execution.
 */
export function checkpointFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  return lifecycleActionFollowUp(status);
}


export function lifecycleActionFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  const lifecycle = typeof status.lifecycle === "string" ? status.lifecycle : null;
  if (lifecycle !== "decision_needed") return undefined;
  // Historical State projections encode waiting for a user as decision_needed.
  // An explicit disposition already closes this turn; it is not missing work.
  if (["user_input_required", "waiting_external", "blocked", "deferred", "terminal", "continue_required"].includes(status.disposition)) return undefined;
  const targets = Array.isArray(status.decision_needed) ? status.decision_needed : [];
  const refs = targets
    .slice(0, 8)
    .map((record) => record?.target_id || record?.target_ref)
    .filter((value) => typeof value === "string" && value)
    .join(", ");
  const suffix = refs ? ` (${refs})` : "";
  return {
    followUp: `Research turn ended with an active scope lacking an explicit disposition${suffix}. Continue the turn: read research_read with mode=context, inspect any relevant Node/Attempt, record a Claim strategy or Attempt interpretation when needed with research_strategy or research_interpretation, then close with research_checkpoint. Do not invent a scientific result and do not end while an active scope has no lifecycle disposition.`,
  };
}

export function requiredLifecycleActions(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return [];
  const candidates = Array.isArray(result.continue_required) ? result.continue_required : [];
  if (candidates.length > 0) {
    const required = candidates.filter((record) => record && typeof record === "object"
      && (record.status === "required" || record.status === "continue_required"
        || record.disposition === "continue_required"));
    const seen = new Set();
    return required.filter((record) => {
      const key = record.id || record.lifecycle_action_id || `${record.scope || ""}:${record.target_id || ""}:${record.action || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  return [];
}
