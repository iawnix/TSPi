"use strict";

async function promptWithDeadline(session, prompt, options = {}) {
  if (!session || typeof session.prompt !== "function" || typeof session.abort !== "function") {
    throw new Error("subagent session must provide prompt() and abort()");
  }
  if (typeof prompt !== "string" || !prompt.trim()) {
    throw new Error("subagent prompt must be a non-empty string");
  }
  const timeoutMs = Number(options.timeoutMs);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1) {
    throw new Error("subagent timeoutMs must be a positive integer");
  }
  const signal = options.signal;
  const abortGraceMs = options.abortGraceMs === undefined ? 5000 : Number(options.abortGraceMs);
  if (!Number.isInteger(abortGraceMs) || abortGraceMs < 1) {
    throw new Error("subagent abortGraceMs must be a positive integer");
  }
  if (signal && signal.aborted) {
    throw interruptionError("TS subagent call aborted by parent", "TS_SUBAGENT_ABORTED");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let interrupted = false;
    let timer;
    let removeAbortListener = () => {};

    const cleanup = () => {
      if (timer) clearTimeout(timer);
      removeAbortListener();
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback(value);
    };
    const interrupt = async (error) => {
      if (settled || interrupted) return;
      interrupted = true;
      cleanup();
      await abortWithGrace(session, abortGraceMs);
      finish(reject, error);
    };

    timer = setTimeout(() => {
      void interrupt(interruptionError(`TS subagent timed out after ${timeoutMs} ms`, "TS_SUBAGENT_TIMEOUT"));
    }, timeoutMs);
    if (signal) {
      const onAbort = () => {
        void interrupt(interruptionError("TS subagent call aborted by parent", "TS_SUBAGENT_ABORTED"));
      };
      signal.addEventListener("abort", onAbort, { once: true });
      removeAbortListener = () => signal.removeEventListener("abort", onAbort);
    }

    Promise.resolve()
      .then(() => session.prompt(prompt, { expandPromptTemplates: false }))
      .then(
        (value) => {
          if (!interrupted) {
            emitLifecycle(options.onLifecycle, "validating");
            finish(resolve, value);
          }
        },
        (error) => {
          if (!interrupted) finish(reject, error);
        },
      );
  });
}

async function abortWithGrace(session, abortGraceMs) {
  let graceTimer;
  try {
    await Promise.race([
      Promise.resolve().then(() => session.abort()).catch(() => {}),
      new Promise((resolve) => {
        graceTimer = setTimeout(resolve, abortGraceMs);
      }),
    ]);
  } finally {
    if (graceTimer) clearTimeout(graceTimer);
  }
}

async function withDisposableSession(createSession, useSession, options = {}) {
  if (typeof createSession !== "function" || typeof useSession !== "function") {
    throw new Error("withDisposableSession requires create and use functions");
  }
  let created;
  try {
    emitLifecycle(options.onLifecycle, "starting");
    created = await createSession();
    emitLifecycle(options.onLifecycle, "running");
    return await useSession(created);
  } finally {
    created?.session?.dispose?.();
  }
}

function emitLifecycle(callback, phase) {
  if (typeof callback !== "function") return;
  try {
    callback(phase);
  } catch {
    // Observability must never change the child-agent execution outcome.
  }
}

function interruptionError(message, code) {
  const error = new Error(message);
  error.code = code;
  return error;
}

module.exports = { promptWithDeadline, withDisposableSession };
