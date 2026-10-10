import { createHash } from "node:crypto";
import { ConversationBusy, defineDoc, defineDocFamily } from "@earendil-works/pi-durable";

export const INPUT_ADMISSION_SERVICE_ID = "coragent.input-admission";

// Immutable provenance complements Pi's submission. No input lifecycle state
// is stored here; acceptance, placement and completion remain Pi-owned.
export const InputProvenance = defineDocFamily({
  kind: "coragent.input-provenance", version: 1, family: true,
  scope: "conversation", history: "latest", fork: "initial", initial: () => ({}),
});
// An index into Pi-owned records, never a copy of their status.
export const InputHead = defineDoc({ kind: "coragent.input-head", version: 1,
  scope: "conversation", history: "latest", fork: "initial", initial: () => ({}) });

const queueModes = { steeringMode: "one-at-a-time", followUpMode: "one-at-a-time" };
const keyFor = requestId => createHash("sha256").update(requestId).digest("hex");
function fail(code, message) { return Object.assign(new Error(message), { code }); }
function requireRequestId(value) {
  if (typeof value !== "string" || !value || value.length > 512) {
    throw fail("invalid_request_id", "Input requires a stable business request ID of at most 512 characters");
  }
  return value;
}
function digest(value) {
  const stable = item => Array.isArray(item) ? item.map(stable) : item && typeof item === "object"
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, stable(item[key])])) : item;
  return createHash("sha256").update(JSON.stringify(stable(value))).digest("hex");
}

/** The Worker supplies trusted producer identity and prepared State evidence. */
export function createInputAdmission({ harness, conversation, LiveDoc, InboxDoc, admitSubmission }) {
  async function status(requestId, context) {
    requireRequestId(requestId);
    const record = await conversation.commit(tx => tx.submissionByRequest(conversation.id, requestId), context);
    return record ?? null;
  }

  async function origin(record, context) {
    return record?.requestId
      ? await harness.snapshot(InputProvenance, conversation.id, keyFor(record.requestId), context) ?? null
      : null;
  }

  async function submit({ requestId, content, whenBusy = "followUp", producer, identity, basis = null, idleOnly = false }, context) {
    requireRequestId(requestId);
    if (!["user", "monitor"].includes(producer)) throw fail("invalid_producer", "Unknown trusted input producer");
    if (!["reject", "steer", "followUp"].includes(whenBusy)) throw fail("invalid_input", "Unsupported input queue policy");
    if (typeof content !== "string" && !Array.isArray(content)) throw fail("invalid_message", "Input content is required");
    const fingerprint = digest({ producer, whenBusy, identity: identity ?? content });
    const admitted = await conversation.commit(async tx => {
      const existing = await tx.submissionByRequest(conversation.id, requestId);
      const provenance = await tx.doc(InputProvenance, conversation.id, keyFor(requestId), null);
      if (existing) {
        if (!provenance.fingerprint) throw fail("input_origin_unavailable", "Input has no verified provenance; create a new session");
        if (existing.type !== "input" || provenance.fingerprint !== fingerprint) {
          throw fail("request_id_reused", "The business input ID already belongs to different content or a different producer");
        }
        return { id: existing.id, duplicate: true };
      }
      if (idleOnly) {
        const [live, inbox] = await Promise.all([tx.doc(LiveDoc, conversation.id), tx.doc(InboxDoc, conversation.id)]);
        if (live.run || inbox.items.length) throw fail("busy", "Internal events wait for an idle session");
      }
      const head = await tx.doc(InputHead, conversation.id);
      // Only Pi reads/writes occur inside this commit. Domain assessment and
      // Python I/O happen before it and are revalidated before consumption.
      const id = await admitSubmission(tx, conversation.id, { type: "input", requestId, content, whenBusy }, Date.now(), queueModes);
      Object.assign(provenance, { producer, fingerprint, identity: identity ?? null, admission_basis: basis });
      head.id = id;
      return { id, duplicate: false };
    }, context);
    harness.resume();
    return admitted;
  }

  return {
    status, origin,
    async checkRecovery(context) {
      const pending = (await harness.inspect(context)).submissions.filter(record => record.conversationId === conversation.id && record.type === "input");
      for (const record of pending) {
        if (!["user", "monitor"].includes((await origin(record, context))?.producer)) {
          throw fail("input_origin_unavailable", "Pending inputs have no verified provenance; create a new session");
        }
      }
    },
    async recordConsumption(record, basis, context) {
      return conversation.commit(async tx => {
        const provenance = await tx.doc(InputProvenance, conversation.id, keyFor(record.requestId), null);
        if (!provenance.fingerprint) throw fail("input_origin_unavailable", "Input has no verified provenance");
        // Append an evidence fact once. Generation tasks change between tool
        // rounds, but this consumed input remains owned by the same Pi run.
        provenance.consumption ??= { submission_id: record.id, basis };
        return provenance.consumption;
      }, context);
    },
    async latest(context) {
      const head = await harness.snapshot(InputHead, conversation.id, context);
      return head?.id ? (await harness.submission(head.id, context))?.status(context) ?? null : null;
    },
    async recoverInternal(requestId, producer, identity, context) {
      const record = await status(requestId, context);
      if (!record) return null;
      const provenance = await origin(record, context);
      if (!provenance?.fingerprint) throw fail("input_origin_unavailable", "Input has no verified provenance; create a new session");
      if (provenance.fingerprint !== digest({ producer, whenBusy: "reject", identity })) {
        throw fail("request_id_reused", "The business input ID already belongs to different content or a different producer");
      }
      return record;
    },
    submitUser: (draft, context) => submit({ requestId: draft.requestId, content: draft.content,
      whenBusy: draft.whenBusy, producer: "user" }, context),
    // Kept on the Worker object, never directly published as a client service.
    submitInternal: (prepared, context) => submit({ ...prepared, idleOnly: true }, context),
  };
}

// Service errors are data: Chord deliberately masks arbitrary remote errors.
export function createInputService(admission) {
  const call = async action => {
    try { return { result: await action(), error: null }; }
    catch (error) { return { result: null, error: { code: error instanceof ConversationBusy ? "busy" : error.code || "input_admission_failed", message: error.message } }; }
  };
  return {
    submit: (draft, context) => call(() => admission.submitUser(draft, context)),
    status: ({ requestId }, context) => call(() => admission.status(requestId, context)),
    latest: context => call(() => admission.latest(context)),
  };
}

/** Native AgentController calls exactly the same admission boundary as Host. */
export function bindUserInputConversation(conversation, admission, harness) {
  return new Proxy(conversation, {
    get(target, property) {
      if (property === "submit") return async (draft, context) => {
        if (draft.type !== "input") return target.submit(draft, context);
        const result = await admission.submitUser(draft, context);
        return harness.submission(result.id, context);
      };
      const value = Reflect.get(target, property, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}
