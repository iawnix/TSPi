import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Pi opens/replaces history before session_start. The launcher must bind the
// first file; cancellable pre-switch hooks keep that binding for its lifetime.
export function registerSessionGuard(pi: ExtensionAPI): void {
  if (process.env.TS_SESSION_GUARD !== "tspi-session-guard/1"
    || process.env.TS_SESSION_WRITER_PID !== String(process.pid)) return;
  const reason = "This TSPi process owns one conversation. Exit and reopen with --session-id <id>; create new conversations in Phone or a new TSPi launch.";
  pi.on("session_before_switch", (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.notify(reason, "warning");
    return { cancel: true };
  });
  pi.on("session_before_fork", (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.notify(reason, "warning");
    return { cancel: true };
  });
}
