# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`ResearchAgent --workspace <name>` is the public launcher for Pi's official remote
`ExperimentalClientTui`. It uses Pi's editor, transcript rendering, and input loop.
This is a separate presentation from ordinary Pi `InteractiveMode`, with its own
command and plugin capabilities. The selected workspace is
bound to one installation-level Pi Harness SQLite durable session.

New workspaces may be explicitly bound to one immutable framework mode:

```bash
./ResearchAgent --workspace quick-task --mode light
./ResearchAgent --workspace reaction-a --mode research
```

`light` creates the minimal workspace profile. `research` creates the Research
Research State state and performs Host admission before the terminal session starts.
For an existing framework workspace, omitting `--mode` uses the recorded mode;
a workspace cannot be converted between modes.

## Runtime shape

There is one Agent Server owner and several clients:

```text
TS Phone/Web -- Link/HTTP --+      TSPi Agent Server / Host API
Pi native TUI -- Unix/SSH ---+-->   Root Agent Session
Monitor -- Host RPC ---------+      Harness / Pi App Server / SessionWorker
```

The Host is the Agent Server API and hosting layer. It owns routing, authentication,
idempotency receipts, scheduler leases, session discovery, transactions, and
the Monitor supervisor. The Pi Harness worker inside that same Agent Server
owns the Root Agent loop, model, tools, transcript, and durable SQLite lane.
The native Pi TUI, Phone, and Monitor all address that same lane; none starts
another agent loop.

The Host client's RPC transport can be a local Unix socket or an SSH-launched
`tspi-host-proxy`, which forwards the same `tspi-host/1` NDJSON over SSH
stdin/stdout to a private remote socket. SSH changes the connection path, not
the owner of the workspace, session, or Agent lane.

For a remote installation, provide the remote Host socket and the proxy path:

```bash
./ResearchAgent --workspace reaction-a \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/tspi/host.sock \
  --remote-proxy-path /opt/tspi/apps/app-server/tspi-host-proxy.mjs \
  --ssh-config ~/.ssh/config
```

The launcher uses the same SSH proxy for the Pi App Server socket returned by
Host, then gives Pi a private local Unix endpoint. The workspace and session
remain on the remote Host; the local directory is only a presentation cwd.

## Open a workspace

```bash
./ResearchAgent --workspace reaction-a
./ResearchAgent --workspace reaction-a -c
```

The launcher first ensures the installation Host is ready, then requests a
session descriptor and execs Pi's native client directly against the Pi App
Server socket. Native Pi Harness is the only supported backend: no tmux
session or PTY scraping path is available. A second terminal
attaches to the same SQLite durable session; closing a client does not stop the
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
switches to another SQLite durable session in the current workspace; it does not
cross workspace boundaries. Switching disposes the old terminal connection before
attaching the selected session; background tasks continue. Other standalone Pi
session commands are not available in this remote client.

TSPi command names, arguments, and completions share one catalogue:

- `/research [summary|context|liveness|map|decisions|storage|detail <kind> <id>|locate <query>|validate|operations]`: read-only queries in the attached worker, including a remote workspace over SSH. Long results use the native Pi selector for paging.
- `/sys-prompt`: inspect the current worker's TSPi system prompt manifest and sources without a model request.
- `/resume [session-id]`: select or specify a session in the current workspace. Cancelling keeps the current session.
- `/quit`: disconnect this terminal while leaving the worker and its tasks running.

The nonfunctional `/debug` placeholder has been removed.

At launch, `-c` selects the latest writable SQLite durable session and
`--session-id <id>` selects an exact session. Startup `-r`/`--resume` is
rejected because the Host-mediated client must obtain an exact connection
descriptor before starting the TUI; open the terminal and use `/resume`
instead. Phone and Web prompts are submitted through Host `input/send` with a
durable request receipt and a stable `client_message_id`.

Prompt history is restored from the selected session's active transcript and remains
session-scoped; use the editor's Up/Down keys to revisit accepted prompts after
switching. On reopening, inputs outside the active transcript after compaction are
not restored.

Disconnect, interrupt, and quit are different states. A detached terminal is
only a disconnected client. `Esc` or Host `turn/interrupt` requests an active
turn interruption. `/quit` closes only this terminal connection. If a request loses the connection after
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

`workspace_manifest.json` binds the canonical `workspace_id` to both scientific
state and Host routing. There is no separate scientific identity or direct-child
alias translation.

## Session storage

The installation-level `var/state/pi/sessions/` tree is the only
session store used by Native Pi Harness. Workspace `.pi/sessions` history is not a
supported input and is neither resumed nor imported by the Native runtime. Durable
history lives in `var/state/pi/sessions/<workspace-id>/<session-id>/session.sqlite`;
metadata is in the adjacent `meta.json`. Keep research state in the workspace
Research Memory and use the Host session controls for SQLite durable sessions.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
service, package, and recovery details.
