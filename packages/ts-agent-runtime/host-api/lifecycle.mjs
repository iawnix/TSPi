/**
 * Transport-neutral helpers for the Research Turn boundary.
 *
 * The Kernel remains the authority for lifecycle state. These functions only
 * reduce its bounded liveness read model into a Host/adapter follow-up.
 */

export const RESEARCH_LIFECYCLE_STATES = Object.freeze([
  "idle",
  "required",
  "decision_needed",
  "waiting_external",
  "deferred",
  "blocked",
  "terminal",
]);

/**
 * Host-owned phases for one domain-neutral Research Turn. `wake` identifies a
 * Monitor-triggered run; it deliberately admits only the orient/read tools.
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

const DEFAULT_TOOL_PHASES = Object.freeze(["orient", "advance", "prepare", "execute", "interpret", "checkpoint"]);

/**
 * Create the Host-side lifecycle admission state for a live Harness lane.
 *
 * The Agent can request a tool, but it cannot choose the phase policy. The
 * before-tool hook calls `admitTool`, this controller advances only along the
 * bounded phase graph, and the private context provider exposes the resulting
 * policy to the execution gate immediately before the implementation runs.
 */
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
  };

  function beginRun({ runId, messages = [], trigger, replay_mode: requestedReplayMode } = {}) {
    if (typeof runId !== "string" || !runId.trim()) throw new TypeError("lifecycle runId must be a non-empty identifier");
    const inferredTrigger = trigger || (isMonitorWake(messages) ? "monitor.wake" : "agent.prompt");
    const effectiveReplayMode = requestedReplayMode || replayMode;
    if (!["normal", "recovery", "reconcile"].includes(effectiveReplayMode)) {
      throw new TypeError(`unsupported lifecycle replay mode: ${effectiveReplayMode}`);
    }
    state = {
      run_id: runId,
      trigger: inferredTrigger,
      lifecycle_phase: inferredTrigger === "monitor.wake" ? "wake" : "orient",
      replay_mode: effectiveReplayMode,
      last_tool: null,
      phase_before_tool: null,
    };
    return snapshot();
  }

  function admitTool({ runId, toolName } = {}) {
    ensureRun(runId);
    const metadataForTool = toolMetadata[toolName];
    if (!metadataForTool) return { accepted: true, ignored: true, ...snapshot() };
    const targetPhase = metadataForTool.phase;
    const allowed = allowedToolPhases(state.lifecycle_phase);
    if (!allowed.includes(targetPhase)) {
      return {
        accepted: false,
        code: "tool_phase_transition_denied",
        reason: `lifecycle phase ${state.lifecycle_phase} cannot admit ${toolName} (${targetPhase})`,
        expected_phases: allowed,
        ...snapshot(),
      };
    }
    state = {
      ...state,
      lifecycle_phase: targetPhase === "orient" && state.lifecycle_phase === "wake" ? "wake" : targetPhase,
      last_tool: toolName,
      phase_before_tool: state.lifecycle_phase,
    };
    return { accepted: true, ...snapshot() };
  }

  function completeTool({ runId, toolName, isError = false } = {}) {
    ensureRun(runId);
    if (isError) {
      if (state.last_tool === toolName && state.phase_before_tool) {
        state = { ...state, lifecycle_phase: state.phase_before_tool, phase_before_tool: null };
      }
      return snapshot();
    }
    const metadataForTool = toolMetadata[toolName];
    if (!metadataForTool) return snapshot();
    const phase = metadataForTool.phase;
    const nextPhase = phase === "orient" || phase === "advance" || phase === "prepare"
      ? "prepare"
      : phase === "execute"
        ? "interpret"
        : phase === "interpret"
          ? "checkpoint"
          : "checkpoint";
    state = { ...state, lifecycle_phase: nextPhase, phase_before_tool: null };
    return snapshot();
  }

  function contextPatch() {
    return {
      operation_id: state.run_id,
      lifecycle_phase: state.lifecycle_phase,
      replay_mode: state.replay_mode,
      allowed_authorities: authorities.length ? authorities : ["host_read"],
      allowed_effects: effects.length ? effects : ["read"],
      allowed_phases: allowedToolPhases(state.lifecycle_phase),
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

  return Object.freeze({ beginRun, admitTool, completeTool, contextPatch, snapshot });
}

function allowedToolPhases(phase) {
  switch (phase) {
    case "wake": return ["orient"];
    case "orient": return ["orient", "advance", "prepare"];
    case "advance": return ["orient", "advance", "prepare", "checkpoint"];
    case "prepare": return ["orient", "prepare", "execute", "interpret", "checkpoint"];
    case "execute": return ["orient", "execute", "interpret", "checkpoint"];
    case "interpret": return ["orient", "advance", "prepare", "interpret", "checkpoint"];
    case "checkpoint": return ["checkpoint"];
    default: return [...DEFAULT_TOOL_PHASES];
  }
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
 * or has closed it.  Hosts must not turn an already-valid `required` state
 * into an immediate same-turn execution.
 */
export function checkpointFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  if (status.lifecycle !== "decision_needed") return undefined;
  return continuationFollowUp(status);
}

export function continuationFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  const required = requiredContinuations(status);
  const lifecycle = typeof status.lifecycle === "string" ? status.lifecycle : null;
  if (required.length === 0 && lifecycle !== "decision_needed") return undefined;

  if (lifecycle === "decision_needed") {
    const targets = Array.isArray(status.decision_needed) ? status.decision_needed : [];
    const refs = targets
      .slice(0, 8)
      .map((record) => record?.target_id || record?.target_ref)
      .filter((value) => typeof value === "string" && value)
      .join(", ");
    const suffix = refs ? ` (${refs})` : "";
    return {
      followUp: `Research turn ended with an active scope lacking an explicit disposition${suffix}. Continue the turn: read ts_state with mode=context, inspect any relevant Node/Attempt, record a Claim strategy or Attempt interpretation when needed with ts_workflow, then close with ts_workflow operation=checkpoint (use operation=set_required only for the legacy continuation ledger; deferred, blocked, or completed are explicit dispositions). Do not invent a scientific result and do not end while an active scope has no lifecycle disposition.`,
    };
  }

  const refs = required
    .slice(0, 8)
    .map((record) => record?.id || record?.continuation_id || record?.target_ref || record?.target_id)
    .filter((value) => typeof value === "string" && value)
    .join(", ");
  const suffix = refs ? ` (${refs})` : "";
  return {
    followUp: `Kernel has ${required.length} required continuation record${required.length === 1 ? "" : "s"}${suffix}. Continue the research turn: first read ts_state with mode=context (or mode=liveness), then read ts_workflow with operation=status, perform the recorded action, and explicitly set its disposition to deferred, blocked, or completed. Do not end while a safe, explicit next step remains.`,
  };
}

export function requiredContinuations(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return [];
  const candidates = [result.required, result.continuations, result.records, result.items]
    .filter((value) => Array.isArray(value))
    .flat();
  if (candidates.length > 0) {
    const required = candidates.filter((record) => record && typeof record === "object"
      && (record.status === "required" || record.disposition === "required"));
    const seen = new Set();
    return required.filter((record) => {
      const key = record.id || record.continuation_id || `${record.scope || ""}:${record.target_id || ""}:${record.action || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  return Number.isInteger(result.required_count) && result.required_count > 0
    ? Array.from({ length: Math.min(result.required_count, 8) }, () => ({ status: "required" }))
    : [];
}
