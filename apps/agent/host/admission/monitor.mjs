import { timingSafeEqual } from "node:crypto";

export const MONITOR_ADMISSION_SERVICE_ID = "coragent.monitor-admission";
const fail = (code, message) => Object.assign(new Error(`${code}: ${message}`), { code });

/** Assess durable delivery identity outside Pi commits. Only authenticated producers reach admission. */
export function createMonitorAdmission({ admission, kernel, sessionId, wakeMessage, producerToken }) {
  function authenticate(token) {
    const expected = Buffer.from(producerToken || "");
    const actual = Buffer.from(typeof token === "string" ? token : "");
    if (!expected.length || actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      throw fail("internal_producer_required", "Internal admission requires the supervised producer identity");
    }
  }
  const assess = async id => {
    const result = await kernel.execute_command("job.monitor_assess", { event_id: id, session_id: sessionId });
    if (typeof result?.admitted !== "boolean" || !result.delivery_token) {
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
      return { accepted: false, error: { code: "monitor_input_failed", message: String(record.detail || record.reason) } };
    }
    return { ...accepted(record), pending: true };
  }
  return {
    admit: ({ requestId, eventIds, token, mode }, context) => response(async () => {
      authenticate(token);
      if (mode !== "next_run") throw fail("invalid_monitor_mode", "Monitor admission requires mode=next_run");
      const identity = eventIdentity(eventIds);
      const existing = await admission.recoverInternal(requestId, "monitor", identity, context);
      if (existing) return monitorResult(existing, identity, context);
      const events = await Promise.all(identity.event_ids.map(assess));
      if (events.some(event => !event.obsolete && !event.admitted)) {
        return { accepted: false, pending: true, assessments: events,
          error: { code: "monitor_paused", message: "Automatic delivery is paused; events remain pending" } };
      }
      const active = events.filter(event => event.admitted);
      if (!active.length) return { accepted: true, skipped: true };
      const basis = Object.fromEntries(events.map(event => [event.event_id, event.delivery_token]));
      await admission.submitInternal({ requestId, producer: "monitor", identity, basis,
        content: active.map(event => wakeMessage(event.event)).join("\n\n"), whenBusy: "reject" }, context);
      return monitorResult(await admission.status(requestId, context), identity, context);
    }),
    // Called before first model consumption. The evidence belongs to the
    // submission and survives generation-task changes and Worker recovery.
    async validateConsumption(record, origin, api, context) {
      if (origin.consumption) return;
      let basis;
      if (origin.producer === "monitor") {
        const events = await Promise.all(origin.identity.event_ids.map(assess));
        const active = events.filter(event => !event.obsolete);
        if (!active.length) {
          throw fail("monitor_superseded", "Monitor input is no longer eligible in the delivery outbox");
        }
        basis = Object.fromEntries(events.map(event => [event.event_id, event.delivery_token]));
      } else { throw fail("invalid_producer", "Only Monitor inputs are internal"); }
      await admission.recordConsumption(record, basis, context);
    },
  };
}
