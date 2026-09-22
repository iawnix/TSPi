# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`TSPi --workspace <name>` is a launcher for Pi's official remote
`ExperimentalClientTui`. It does not replace Pi's header, editor, command
registry, transcript view, extensions, or input loop. The selected workspace is
bound to one installation-level Pi Harness format-4 session; old format-3 files under
`<workspace>/.pi/sessions/` are read-only compatibility history.

## Runtime shape

There is one runtime owner and several clients:

```text
Pi App Server / SessionWorker  <->  TSPi Host  <->  TS Phone/Web
       AgentHarness + transcript       Host RPC       Link/HTTP
                 ^                         ^
          Pi native TUI                Monitor
```

The Pi Harness worker owns the agent loop, model, tools, transcript, and
durable format-4 lane. The Host owns routing, authentication, idempotency receipts,
scheduler leases, session discovery, and the Monitor supervisor. The native Pi
TUI, Phone, and Monitor all address that same lane; none starts another agent
loop.

## Open a workspace

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

The launcher first ensures the installation Host is ready, then requests a
session descriptor and execs Pi's native client directly against the Pi App
Server socket. No tmux session, PTY scraping, or ordinary bridge is involved in
the default path. A second terminal attaches to the same format-4 session; closing a
client does not stop the worker or interrupt a turn. The explicit
`TSPI_HOST_BACKEND=ordinary` setting remains only for migration/debug checks.

The Host service is installation-wide and scans direct child workspaces. It is
normally managed with:

```bash
systemctl --user start ts-app-server-tspi.service
systemctl --user status ts-app-server-tspi.service
```

Use the same commands without `--user` for a system unit. The private Host
socket is under the configured runtime directory and the bridge token is under
`.pi/app-server-host/`.

## Sessions and controls

Pi's `/new`, `/resume`, `/fork`, `/model`, `/settings`, and extension commands
remain Pi commands. `-c` selects the latest writable format-4 session in this
workspace; `--session-id <id>` selects an exact session. Phone and Web prompts
are submitted through Host `input/send` with a durable request receipt and a
stable `client_message_id`.

Disconnect, interrupt, and quit are different states. A detached terminal is
only a disconnected client. `Esc` or Host `turn/interrupt` requests an active
turn interruption. `/quit` ends Pi. If a request loses the connection after
dispatch, Host reports `uncertain` and does not silently replay it; an on-disk
`dispatching` receipt is also not reported as accepted until Pi has reached the
submitted/observed boundary. Inspect the session before retrying with the same
business ID.

## Phone and browser

TS Phone uses the versioned `tspi-host/1` NDJSON methods through TSPi Link. The
Relay transports opaque frames and does not own sessions or research state.
Phone and the terminal receive the same Pi snapshot and events. The optional
browser gateway attaches to one existing session over loopback HTTP/SSE; it
does not start Pi or a worker.

## Monitor

The Host starts one Monitor worker for the configured workspace root. Monitor
ticks durable Compute status and writes event and delivery receipts inside each
workspace. Wake and user-notification channels are acknowledged independently,
with leases and backoff. A wake is an accepted input, not proof that an agent
turn finished; the Root Agent must reread state and inspect the calculation.
Monitor never finalizes a calculation or edits `ResearchMap`.

`workspace.json` has a stable scientific identity such as `ws_<hex>`. Host RPC
addresses the direct-child directory name such as `reaction-a`; Monitor verifies
the canonical identity before translating it to that route name.

## Legacy histories

The installation-level `.pi/app-server-host/sessions/` tree is the only
canonical format-4 store. Workspace `.pi/sessions/*.jsonl` format-3 files are listed and
readable but cannot be resumed or prompted. Use
`apps/app-server/tspi-history.mjs --source ... --import` (or Host
`session/import`) for an explicit source-digest-checked format-3 to format-4 import; the
source is never modified and a provenance report is written under the
installation Host state. Unknown, torn, active, or conflicting history is
rejected instead of silently replayed.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
service, package, and recovery details.
