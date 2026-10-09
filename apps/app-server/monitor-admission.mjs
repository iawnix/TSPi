import { timingSafeEqual } from "node:crypto";

export const MONITOR_ADMISSION_SERVICE_ID = "tspi.monitor-admission";
const continuationMessage = "Research State requests continuation of authorized work. Read research_read mode=context and advance the existing plan. Reuse Job identities; reconcile existing Attempts before retrying. End with the appropriate checkpoint when waiting, blocked, or complete.";
const fail = (code, message) => Object.assign(new Error(`${code}: ${message}`), { code });
const stateToken = state => `${state.revision}:${state.checkpoint_id ?? "None"}`;

/** Assess State outside Pi commits. Only authenticated producers reach admission. */
export function createMonitorAdmission({ admission, kernel, sessionId, wakeMessage, producerToken }) {
  function authenticate(token) {
    const expected = Buffer.from(producerToken || "");
    const actual = Buffer.from(typeof token === "string" ? token : "");
    if (!expected.length || actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      throw fail("internal_producer_required", "Internal admission requires the supervised producer identity");
    }
  }
  const assess = async id => {
    const result = await kernel.execute_command("research.monitor_assess", { event_id: id, session_id: sessionId });
    if (typeof result?.admitted !== "boolean" || !result.state_token) {
      throw fail("invalid_monitor_assessment", "Invalid Monitor assessment");
    }
    return result;
  };
  function eventIdentity(ids) {
    if (!Array.isArray(ids) || !ids.length || ids.length > 256 || ids.some(id => typeof id !== "string" || !/^event_[A-Za-z0-9_-]+$/u.test(id))) {
      throw fail("invalid_monitor_events", "Monitor input requires structured eventIds");
    }
    return { event_ids: [...new Set(ids)].sort() };
  }
  const response = async action => {
    try { return await action(); }
    catch (error) { return { accepted: false, error: { code: error.code || "internal_admission_failed", message: error.message } }; }
  };
  const accepted = record => ({ accepted: true, operation_id: String(record.id) });
  async function monitorResult(record, identity, context) {
    const origin = await admission.origin(record, context);
    if (origin?.consumption) return { ...accepted(record), consumed: true };
    if (record.status === "unanswered") {
      if (record.reason === "request_blocked" && typeof record.detail === "string" && record.detail.includes("monitor_superseded:")) {
        const assessments = await Promise.all(identity.event_ids.map(assess));
        if (assessments.every(event => event.obsolete)) return { accepted: true, skipped: true };
        return { accepted: false, superseded: true, assessments,
          error: { code: "monitor_deferred", message: "Monitor input was superseded before consumption" } };
      }
      return { accepted: false, error: { code: "monitor_input_failed", message: String(record.detail || record.reason) } };
    }
    return { ...accepted(record), pending: true };
  }
  return {
    admit: ({ requestId, eventIds, token }, context) => response(async () => {
      authenticate(token);
      const identity = eventIdentity(eventIds);
      const existing = await admission.recoverInternal(requestId, "monitor", identity, context);
      if (existing) return monitorResult(existing, identity, context);
      const events = await Promise.all(identity.event_ids.map(assess));
      if (events.some(event => !event.obsolete && !event.admitted)) {
        return { accepted: false, assessments: events,
          error: { code: "monitor_deferred", message: "Research State deferred this Monitor batch" } };
      }
      const active = events.filter(event => event.admitted);
      if (!active.length) return { accepted: true, skipped: true };
      const basis = Object.fromEntries(events.map(event => [event.event_id, event.state_token]));
      await admission.submitInternal({ requestId, producer: "monitor", identity, basis,
        content: active.map(event => wakeMessage(event.event)).join("\n\n"), whenBusy: "reject" }, context);
      return monitorResult(await admission.status(requestId, context), identity, context);
    }),
    admitContinuation: ({ requestId, token }, context) => response(async () => {
      authenticate(token);
      const identity = { continuation_id: requestId };
      const existing = await admission.recoverInternal(requestId, "state_continuation", identity, context);
      if (existing) return accepted(existing);
      const state = await kernel.read_liveness({});
      const next = state?.continuation;
      if (next?.admitted !== true || next.request_id !== requestId || next.session_id !== sessionId) {
        throw fail("continuation_superseded", "No current continuation is available");
      }
      return accepted(await admission.submitInternal({ requestId, producer: "state_continuation", identity,
        basis: stateToken(state), content: continuationMessage, whenBusy: "reject" }, context));
    }),
    async readContinuation({ token }, context) {
      authenticate(token);
      context?.abortSignal?.throwIfAborted();
      return kernel.read_liveness({});
    },
    // Called before first model consumption. The evidence belongs to the
    // submission and survives generation-task changes and Worker recovery.
    async validateConsumption(record, origin, api, context) {
      if (origin.consumption) return;
      let basis;
      if (origin.producer === "monitor") {
        const events = await Promise.all(origin.identity.event_ids.map(assess));
        const active = events.filter(event => event.admitted);
        if (!active.length || events.some(event => !event.obsolete && !event.admitted)) {
          throw fail("monitor_superseded", "Monitor input is no longer eligible in current Research State");
        }
        basis = Object.fromEntries(events.map(event => [event.event_id, event.state_token]));
      } else {
        const state = await kernel.read_liveness({});
        const next = state?.continuation;
        if (next?.admitted !== true || next.request_id !== record.requestId || next.session_id !== sessionId) {
          throw fail("continuation_superseded", "Continuation input is no longer current");
        }
        basis = stateToken(state);
      }
      await admission.recordConsumption(record, basis, context);
    },
  };
}
