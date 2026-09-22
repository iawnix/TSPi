# ADR 0005: Ordinary Pi Runtime With a Host Bridge

[English](0005-ordinary-pi-host-bridge.md) | [简体中文](0005-ordinary-pi-host-bridge.zh-CN.md)

- Status: accepted for migration/debug compatibility only; not the default runtime
- Date: 2026-09-21
- Scope: TSPi launcher, Pi terminal, Host, Phone, Web, Monitor, and history

## Decision

This ADR records the transitional ordinary-Pi compatibility mode. When
`TSPI_HOST_BACKEND=ordinary` is explicitly selected, `TSPi --workspace <name>`
launches the pinned Pi CLI in its normal `InteractiveMode`. Pi owns the agent
loop, model, tools, format-3 transcript, cwd, and workspace Root lock. TSPi
loads ordinary research extensions plus one small bridge extension. This mode
has an isolated writer and is never used as a Harness fallback.

The default runtime is the installation Pi App Server described by the Harness
architecture: one `SessionWorker`/`AgentHarness` lane is shared by the native
Pi remote TUI, Phone, and Monitor clients.

The installation Host is a control plane, not a second Pi runtime. It exposes
authenticated `tspi-host/1` NDJSON over a private Unix socket and provides
workspace/session discovery, input admission, idempotency receipts, event
subscriptions, model selection, and Monitor supervision. The bridge translates
Host requests to the live Pi ExtensionAPI and publishes native snapshots and
events back. One live Pi process is allowed per workspace.

The ordinary compatibility mode may use `tmux` as its persistence boundary,
but this is an explicit migration/debug concern. The Harness path never starts
tmux or scrapes a PTY. If the compatibility mode cannot use tmux it may run Pi
in the foreground; that process must not write the Harness format-4 repository.

TS Phone uses Host RPC through TSPi Link. The Relay forwards opaque framed
NDJSON and owns neither sessions nor research state. The optional browser
gateway is a loopback adapter to one existing Host session.

The Host starts one Monitor worker for the workspace root. Monitor writes
durable registrations, events, and per-channel delivery receipts. Wake and
notification delivery are independent, leased, retryable, and deduplicated.
An accepted wake is not an agent completion. Monitor never finalizes a
calculation or writes ResearchMap state.

Scientific `workspace.json` identity (`ws_<hex>`) is distinct from Host's route
identity (the direct-child directory name). A worker verifies ownership before
translating between them.

Compatibility history is never silently converted or opened writable. Host
exposes workspace format-3 files read-only; an explicit import creates a new
installation-owned format-4 session while preserving the source and writing a
provenance report. Ambiguous, active, torn, or unsupported histories are
rejected.

## Consequences

- Pi behavior and commands remain available without TSPi-specific rendering.
- Phone, Web, and Monitor share a live Pi session without owning a second agent.
- `request_id` and `client_message_id` make retries observable; uncertain input
  is not blindly replayed.
- The compatibility mode remains isolated from Harness receipts, history, and
  locks; it is removed once migration support is no longer needed.
- The default Harness terminal has no tmux dependency and reconnects through a
  local Pi connection descriptor after Host recovery.
