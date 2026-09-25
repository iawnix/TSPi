# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`TSPi --workspace <name>` is a launcher for Pi's official remote
`ExperimentalClientTui`. It does not replace Pi's header, editor, command
registry, transcript view, extensions, or input loop. The selected workspace is
bound to one installation-level Pi Harness format-4 session.

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
Server socket. Native Pi Harness is the only supported backend: no tmux
session or PTY scraping path is available. A second terminal
attaches to the same format-4 session; closing a client does not stop the
worker or interrupt a turn.

The Host service is installation-wide and scans direct child workspaces. It is
normally managed with:

```bash
systemctl --user start ts-app-server-tspi.service
systemctl --user status ts-app-server-tspi.service
```

Use the same commands without `--user` for a system unit. The private Host
socket is under the configured runtime directory.

## Sessions and controls

The remote `ExperimentalClientTui` provides `/resume`, `/model`, `/thinking`,
`/compact`, `/reload`, and the Native TSPi commands. `/resume`
switches to another format-4 session in the current workspace; it does not
cross workspace boundaries. Standalone Pi session commands are not available
in this remote client.

At launch, `-c` selects the latest writable format-4 session and
`--session-id <id>` selects an exact session. Startup `-r`/`--resume` is
rejected because the Host-mediated client must obtain an exact connection
descriptor before starting the TUI; open the terminal and use `/resume`
instead. Phone and Web prompts are submitted through Host `input/send` with a
durable request receipt and a stable `client_message_id`.

Prompt history is restored from the selected session and remains session-scoped;
use the editor's Up/Down keys to revisit accepted prompts after switching.

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

## Session storage

The installation-level `.pi/app-server-host/sessions/` tree is the only
session store used by Native Pi Harness. Workspace `.pi/sessions/*.jsonl`
history is not a supported input and is neither resumed nor imported by the
Native runtime. Keep research state in the workspace Research Memory and use
the Host session controls for format-4 sessions.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
service, package, and recovery details.
