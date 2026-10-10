# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`research-agent --workspace <name>` is the public launcher for Pi's official remote
`ExperimentalClientTui`. It uses Pi's editor, transcript rendering, and input loop.
This is a separate presentation from ordinary Pi `InteractiveMode`, with its own
command and plugin capabilities. The selected workspace is
bound to one installation-level Pi Harness SQLite durable session.

Workspaces use the research mode automatically. No mode selection is needed; see the workspace commands below.

## Runtime shape

There is one Agent Server owner and several clients:

```text
TS Phone/Web -- Link/HTTP --+      ResearchAgent Agent Server / Host API
Pi native TUI -- Unix/SSH ---+-->   Root Agent Session
Monitor -- Host RPC ---------+      Harness / Pi App Server / SessionWorker
```

The Host is the Agent Server API and hosting layer. It owns routing, authentication,
session discovery, non-input RPC receipts, and
the Monitor supervisor. The Pi Harness worker inside that same Agent Server
owns input admission and idempotency, the Root Agent loop, model, tools, transcript, and durable SQLite lane.
The native Pi TUI, Phone, and Monitor all address that same lane; none starts
another agent loop.

The Host client's RPC transport can be a local Unix socket or an SSH-launched
`research-agent-host-proxy`, which forwards the same `research-agent-host/2` NDJSON over SSH
stdin/stdout to a private remote socket. SSH changes the connection path, not
the owner of the workspace, session, or Agent lane.

For a remote installation, provide the remote Host socket and the proxy path:

```bash
./research-agent --workspace reaction-a \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/research-agent/host.sock \
  --remote-proxy-path /opt/research-agent/apps/agent/transport/ssh.mjs \
  --ssh-config ~/.ssh/config
```

The launcher uses the same SSH proxy for the Pi App Server socket returned by
Host, then gives Pi a private local Unix endpoint. The workspace and session
remain on the remote Host; the local directory is only a presentation cwd.

## Open a workspace

```bash
./research-agent --workspace reaction-a
./research-agent --workspace reaction-a -c
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
systemctl --user start ts-app-server-research-agent.service
systemctl --user status ts-app-server-research-agent.service
```

Use the same commands without `--user` for a system unit. The private Host
socket is under the configured runtime directory.

## Sessions and controls

The remote `ExperimentalClientTui` provides `/resume`, `/model`, `/thinking`,
`/compact`, `/reload`, and the Native ResearchAgent commands. `/resume`
switches to another SQLite durable session in the current workspace; it does not
cross workspace boundaries. Switching disposes the old terminal connection before
attaching the selected session; background tasks continue. Other standalone Pi
session commands are not available in this remote client.

Selectors and document views own keyboard focus while open. Arrow keys navigate
and Esc returns to the editor, preserving its draft and cursor even after mouse
interaction. Execution commands such as `/compact` and `/reload` use a single
status line and leave the editor usable; no panel needs to be dismissed.
`/compact` tracks its durable operation until the summary is placed, or reports
that it was skipped, cancelled, or failed. The transcript shows a compacted
context marker; it does not print the internal summary as an ordinary reply.

ResearchAgent command names, arguments, and completions share one catalogue:

- `/research`: read-only queries in the attached worker, for Memory context and records, including a remote workspace over SSH. Use the command help for supported selectors. Long results open a separate reading page.
- `/sys-prompt`: inspect the current worker's ResearchAgent system prompt manifest and sources without a model request.
- `/resume [session-id]`: select or specify a session in the current workspace. Cancelling keeps the current session.
- `/usage`: inspect session token totals, context and usage by model in a compact panel.
- `/monitor`: inspect this session's running and queued jobs, pending deliveries and last check in a live panel.
- `/quit`: disconnect this terminal while leaving the worker and its tasks running.

The nonfunctional `/debug` placeholder has been removed.

Successful command feedback expires after three seconds and informational feedback
after five; errors remain until dismissed or another input is submitted. Submitting
a message clears completed command feedback. With a selector or document open, Esc
returns to chat. In ordinary chat, Esc interrupts the running turn even when command
feedback is visible.

Usage and monitor panels, model/thinking/resume selectors, and slash completions
open above the Monitor row. The system prompt and long research results replace the
main reading area, with a fixed heading and Back/scroll hints. Every screen retains
Monitor, the input and the model/context footer. The input preserves its draft and
cursor but cannot be edited or focused while a panel or reading page is open.
Arrow keys scroll content without changing the panel height; short documents only
show Back. Closing restores editing and the transcript reading position. Background
task cancellation hints are hidden while a command surface owns Esc.

A permanent row immediately above the input shows `Monitor ✓` (healthy),
`Monitor …` (checking or briefly reconnecting),
`Monitor !` (warning), or `Monitor ×` (error). `· ⚙2` means two jobs are running in this
session; queued jobs are counted separately in `/monitor`. `⚙0` means none are running
and `⚙—` means the count is unavailable. An optional `· ↑N` counts monitor events
awaiting delivery; ordinary pending delivery is not a warning. The row remains
visible when idle and during command use. Completion lists retain Pi's keyboard and
mouse behavior in their own area above it. Background refreshes preserve selection,
reading position and input focus. Terminal resizing and multiline drafts move the
row with the input; opening a command does not move it away from the input.
`/monitor` shows job counts, warning reasons and the last
successful poll. Counts belong to this session; worker health is shared across workspaces.

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
turn interruption. `/quit` closes only this terminal connection. If an input response is lost after dispatch, query `input/status` with the
same `client_message_id`. Pi's durable submission owns acceptance and completion;
retrying the same business ID does not create another input.

## Phone and browser

Phone clients must implement the versioned `research-agent-host/2` NDJSON methods through ResearchAgent Link. The
Relay transports opaque frames and does not own sessions or research state.
Phone and the terminal receive the same Pi snapshot and events. The optional
browser gateway attaches to one existing session over loopback HTTP/SSE; it
does not start Pi or a worker.

Host accepts only `initialize` with `protocol: "research-agent-host/2"`. Version 1 clients
must be updated. Capability names are the callable slash-separated methods.
Session reads and attachments accept only `after_cursor: {epoch, sequence}`;
a different Host epoch returns a current snapshot without replaying old events.
Session creation/resumption and `model/select` use `model: {provider, id}`.
Session lists use `{sessions: [...]}` and contain no legacy backend or format flags.

## Monitor

The Host starts one Monitor worker for the configured workspace root. Monitor
ticks durable Compute status and writes event and delivery receipts inside each
workspace. Wake and user-notification channels are acknowledged independently,
with leases and backoff. A wake is an accepted input, not proof that an agent
turn finished; the Root Agent must reread state and inspect the calculation.
Monitor delivers authenticated execution events through next_run; it does not publish scientific conclusions or edit Node content.

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
