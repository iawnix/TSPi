/**
 * Transport-neutral helpers for the Research Turn boundary.
 *
 * The Kernel remains the authority for lifecycle state. These functions only
 * reduce its bounded liveness read model into a Host/adapter follow-up.
 */

export const RESEARCH_LIFECYCLE_STATES = Object.freeze([
  "idle",
  "continue_required",
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

// Durable Research Kernel liveness is a semantic boundary, not a generic
// `read`/`write` switch. Keep the sets here in sync with the public tool
// metadata registry so a newly named effect cannot accidentally bypass a
// blocked or decision-needed workspace.
const PURE_READ_EFFECTS = new Set(["read"]);
const RESEARCH_DECISION_EFFECTS = new Set([
  "research_write",
  "lifecycle_write",
  "advisory",
  "advisory_disposition",
]);
const EXECUTION_EFFECTS = new Set([
  "attempt_artifact",
  "artifact_write",
  "execution_control",
  "external_write",
]);

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
    if (!metadataForTool) return { accepted: true, ignored: true, ...snapshot() };
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
    const targetPhase = metadataForTool.phase;
    const lifecycle = durableLiveness?.lifecycle;
    const disposition = durableLiveness?.disposition;
    const effect = metadataForTool.effect;
    const isRead = PURE_READ_EFFECTS.has(effect);
    const isDecisionWrite = RESEARCH_DECISION_EFFECTS.has(effect);
    const isExecution = EXECUTION_EFFECTS.has(effect);
    // `compute_run` is one public tool with two distinct lifecycle roles. A
    // follow-up inspect/finalize/cancel acts on an existing Attempt and must be
    // available while that Attempt is waiting for external reconciliation. The
    // launch operation remains an execution side effect and is still blocked.
    const existingAttemptOperation = isExistingAttemptOperation(toolName, args);
    if (lifecycle === "blocked" || disposition === "blocked") {
      // The Kernel permits a checkpoint to replace a blocked disposition. A
      // checkpoint is represented by lifecycle_write plus the checkpoint
      // phase; all other mutations and side effects remain stopped.
      const isRecoveryCheckpoint = isDecisionWrite && targetPhase === "checkpoint";
      if (!isRead && !isRecoveryCheckpoint) {
        return {
          accepted: false,
          code: "research_lifecycle_blocked",
          reason: "durable Research Kernel liveness is blocked",
          ...snapshot(),
        };
      }
    }
    if (disposition === "user_input_required") {
      // User input is a hard stop. Only orientation reads and a checkpoint
      // that records the user's eventual disposition can cross this boundary.
      const isRecoveryCheckpoint = isDecisionWrite && targetPhase === "checkpoint";
      if (!isRead && !isRecoveryCheckpoint) {
        return {
          accepted: false,
          code: "research_user_input_required",
          reason: "durable Research Kernel liveness requires user input",
          ...snapshot(),
        };
      }
    } else if (lifecycle === "decision_needed" || lifecycle === "waiting_external") {
      // The Kernel exposes `execution_ready` after an active StrategyPlan
      // covers the focused scope. That is the same decision boundary enforced
      // by the filesystem adapter; a checkpoint is still required before the
      // turn ends, but execution must be able to follow strategy in the same
      // turn. Waiting for a remote Attempt remains a hard stop.
      const executionReady = lifecycle === "decision_needed"
        && durableLiveness?.execution_ready === true;
      if ((isExecution || (!isRead && !isDecisionWrite)) && !executionReady && !existingAttemptOperation) {
        return {
          accepted: false,
          code: lifecycle === "waiting_external" ? "research_waiting_external" : "research_decision_required",
          reason: lifecycle === "waiting_external"
            ? "durable Research Kernel liveness is waiting for an external Attempt"
            : "durable Research Kernel liveness requires a scientific decision",
          ...snapshot(),
        };
      }
    }
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
      // A monitor wake admits exactly one orient/read tool. Once that read
      // completes, the normal advance graph may inspect the bound Attempt.
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
    // Orientation is followed by the planning/ResearchMap mutation phase;
    // only after an advance is complete do we enter preparation. Re-reading
    // state from a later phase normally returns to that phase. A bounded
    // disposition repair is the exception: after checkpoint the Host may ask
    // for one read-only orientation before accepting a strategy or checkpoint.
    const phaseBeforeTool = state.phase_before_tool || state.lifecycle_phase;
    const nextPhase = isExistingAttemptOperation(toolName, args) && args?.operation === "inspect"
      ? "execute"
      : phase === "orient"
      ? (phaseBeforeTool === "orient" || phaseBeforeTool === "wake" || phaseBeforeTool === "checkpoint" ? "advance" : phaseBeforeTool)
      : phase === "advance" || phase === "prepare"
        ? "prepare"
        : phase === "execute"
          ? "interpret"
          : phase === "interpret"
            // Artifact interpretation (analysis/compare/render) produces
            // evidence that the Agent still needs to record in ResearchMap.
            // Reopen the planning lane for that write, while canonical
            // ResearchMap interpretation/advisory tools still close at a
            // checkpoint.
            ? metadataForTool.effect === "artifact_write" ? "advance" : "checkpoint"
            : "checkpoint";
    state = { ...state, lifecycle_phase: nextPhase, phase_before_tool: null, active_tool_call_id: null };
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

  return Object.freeze({ beginRun, admitTool, completeTool, contextPatch, setDurableLiveness, snapshot });
}

function allowedToolPhases(phase) {
  switch (phase) {
    case "wake": return ["orient"];
    case "orient": return ["orient", "advance", "prepare"];
    // A strategy turn may launch a bounded Attempt after orientation while
    // still admitting explicit strategy/change records in the advance phase.
    case "advance": return ["orient", "advance", "prepare", "execute", "checkpoint"];
    // Preparation can include read-only environment/capability inspection
    // before the Root records the Claim/Node plan. Keep advance reachable so
    // that this valid planning path is not stranded in prepare.
    case "prepare": return ["orient", "advance", "prepare", "execute", "interpret", "checkpoint"];
    case "execute": return ["orient", "execute", "interpret", "checkpoint"];
    case "interpret": return ["orient", "advance", "prepare", "interpret", "checkpoint"];
    // A checkpoint is normally terminal for this run. The liveness repair
    // hook may, however, continue the same Harness run and must first inspect
    // the active scope with the read-only orientation tool.
    case "checkpoint": return ["orient", "checkpoint"];
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
 * or has closed it. Hosts must not turn an already-valid `continue_required`
 * state into an immediate same-turn execution.
 */
export function checkpointFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  if (status.lifecycle !== "decision_needed") return undefined;
  return continuationFollowUp(status);
}

function isExistingAttemptOperation(toolName, args) {
  if (toolName !== "compute_run" && toolName !== "compute_run") return false;
  return ["inspect", "finalize", "cancel"].includes(args?.operation);
}

export function continuationFollowUp(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  const lifecycle = typeof status.lifecycle === "string" ? status.lifecycle : null;
  if (lifecycle !== "decision_needed") return undefined;
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

export function requiredContinuations(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return [];
  // `required` is the canonical continuation-status projection returned by
  // the filesystem Kernel. Keep the older `continue_required` envelope as a
  // read-only input shape for adapters that still emit it, but never make
  // callers know which transport produced the status.
  const candidates = [result.required, result.continue_required]
    .filter((value) => Array.isArray(value))
    .flat();
  if (candidates.length > 0) {
    const required = candidates.filter((record) => record && typeof record === "object"
      && (record.status === "required" || record.status === "continue_required"
        || record.disposition === "continue_required"));
    const seen = new Set();
    return required.filter((record) => {
      const key = record.id || record.continuation_id || `${record.scope || ""}:${record.target_id || ""}:${record.action || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  const count = result.continue_required_count;
  return Number.isInteger(count) && count > 0
    ? Array.from({ length: Math.min(count, 8) }, () => ({ status: "continue_required" }))
    : [];
}
