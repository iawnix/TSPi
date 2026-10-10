# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`coragent --workspace <name>` is the public launcher for Pi's official remote
`ExperimentalClientTui`. It uses Pi's editor, transcript rendering, and input loop.
This is a separate presentation from ordinary Pi `InteractiveMode`, with its own
command and plugin capabilities. The selected workspace is
bound to one installation-level Pi Harness SQLite durable session.

Workspaces use the research mode automatically. No mode selection is needed; see the workspace commands below.

## Runtime shape

There is one Agent Server owner and several clients:

```text
CoRHub/Web -- Link/HTTP --+      CoRAgent Agent Server / Host API
Pi native TUI -- Unix/SSH ---+-->   Root Agent Session
Monitor -- Host RPC ---------+      Harness / Pi App Server / SessionWorker
```

The Host is the Agent Server API and hosting layer. It owns routing, authentication,
session discovery, session-management RPC receipts, and
the Monitor supervisor. The Pi Harness worker inside that same Agent Server
owns input admission and idempotency, user-task control receipts, the Root Agent loop, model, tools, transcript, and durable SQLite lane.
The native Pi TUI, Phone, and Monitor all address that same lane; none starts
another agent loop.

The Host client's RPC transport can be a local Unix socket or an SSH-launched
`coragent-host-proxy`, which forwards the same `coragent-host/2` NDJSON over SSH
stdin/stdout to a private remote socket. SSH changes the connection path, not
the owner of the workspace, session, or Agent lane.

For a remote installation, provide the remote Host socket and the proxy path:

```bash
./coragent --workspace reaction-a \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/coragent/host.sock \
  --remote-proxy-path /opt/coragent/apps/agent/transport/ssh.mjs \
  --ssh-config ~/.ssh/config
```

The launcher uses the same SSH proxy for the Pi App Server socket returned by
Host, then gives Pi a private local Unix endpoint. The workspace and session
remain on the remote Host; the local directory is only a presentation cwd.

## Open a workspace

```bash
./coragent --workspace reaction-a
./coragent --workspace reaction-a -c
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
systemctl --user start coragent.service
systemctl --user status coragent.service
```

Use the same commands without `--user` for a system unit. The private Host
socket is under the configured runtime directory.

## Sessions and controls

The remote `ExperimentalClientTui` provides `/resume`, `/model`, `/thinking`,
`/compact`, `/reload`, and the Native CoRAgent commands. `/resume`
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

Slash completion uses a stable viewport above the editor. Arrow keys select a
candidate; Tab and clicks only complete it. Enter opens a command entry. Enter on
an argument candidate only completes it; a subsequent Enter submits the command.
Esc dismisses completion without clearing the input, and Tab reopens it. Monitor
suggestions follow the current argument position and preserve case-sensitive IDs.
Incomplete commands report the missing argument without executing an operation.

Failed commands return to an untouched editor for correction; late failures never
overwrite a newer draft. Press F2 on an error to read its complete message and
usage, then Esc to return. Paths and multiline text starting with a slash remain
ordinary messages. Pasting alone never executes a command.

Command surfaces follow the active Pi theme. `›` marks keyboard focus and
`[current]` marks the applied value; selectors support clicks and wheel navigation.
Running and queued tools use the activity color, blocked tools use warning,
failures use error, and cancellation uses secondary text. With `NO_COLOR` or
`TERM=dumb`, command surfaces, completion, status and tool summaries keep text and
symbol cues.

CoRAgent command names, arguments, and completions share one catalogue:

- `/research`: read-only queries in the attached worker, for Memory context and records, including a remote workspace over SSH. Use the command help for supported selectors. Long results open a separate reading page.
- `/sys-prompt`: inspect the current worker's CoRAgent system prompt manifest and sources without a model request.
- `/resume [session-id]`: select or specify a session in the current workspace. Cancelling keeps the current session.
- `/usage`: inspect session token totals, context and usage by model in a compact panel.
- `/monitor`: inspect the current user task, its delivery criteria and waits, associated compute Jobs, and execution records. See the Monitor commands below.
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

A permanent row immediately above the input shows the user task before the Job
count: `Monitor ✓ · Researching · 2 jobs running`, `Waiting for compute`,
`Preparing continuation`, `Paused`, `Needs attention`, or `Completed`. A completed
model reply does not imply a completed user task. A disconnected or stale snapshot
takes priority over cached progress. Unknown counts display `—`; no progress
percentage or completion time is inferred. The row remains visible while idle and
while command panels are open. Background refreshes preserve focus, selection,
reading position, and the input draft.

`/monitor` is a live current-session overview. It displays the original objective,
delivery criteria, latest recorded progress, concrete Job waits, control reason,
and automatic-continuation setting. Compute execution and output collection have
separate fields. Scientific analysis shows “Not recorded” until a dedicated
research projection provides evidence; a successful Job is not treated as completed
analysis. Open execution details to inspect Pi generation/tool tasks; they are not
mixed into the user-task list.

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

Phone clients must implement the versioned `coragent-host/2` NDJSON methods through CoRAgent Link. The
Relay transports opaque frames and does not own sessions or research state.
Phone and the terminal receive the same Pi snapshot and events. The optional
browser gateway attaches to one existing session over loopback HTTP/SSE; it
does not start Pi or a worker.

Host accepts only `initialize` with `protocol: "coragent-host/2"`. Version 1 clients
must be updated. Capability names are the callable slash-separated methods.
Session reads and attachments accept only `after_cursor: {epoch, sequence}`;
a different Host epoch returns a current snapshot without replaying old events.
Session creation/resumption and `model/select` use `model: {provider, id}`.
Session lists use `{sessions: [...]}` and contain no legacy backend or format flags.

## Monitor

Monitor unifies user-task controls and compute-Job observations. Task Controller
runs alongside the Pi Harness in the SessionWorker and uses the same durable
transaction and admission boundary. The installation Monitor worker polls Compute
status and records execution events. Pi remains the only model/tool execution loop;
Research Memory stores scientific evidence and conclusions.

| Command | Behavior |
| --- | --- |
| `/monitor` | Live overview for the current session |
| `/monitor tasks` | Current and historical user tasks |
| `/monitor task <id>` | Objective, delivery criteria, research problems, progress and waits |
| `/monitor task pause <id>` | Pause automatic task progression; running work may finish |
| `/monitor task resume <id>` | Resume the specified user task |
| `/monitor task cancel <id> --keep-jobs` | Cancel the user task and retain its compute Jobs |
| `/monitor task cancel <id> --cancel-jobs` | Cancel the user task and request cancellation of its Jobs |
| `/monitor jobs [--task <id>]` | Session Jobs or Jobs owned by one user task |
| `/monitor job <id>` | Execution and collection state |
| `/monitor job cancel <id>` | Request cancellation of one compute Job |
| `/monitor runs [--task <id>]` | Execution records grouped by Pi submission/run |
| `/monitor run <id>` | Bounded generation/tool execution details |
| `/monitor health` | Task Controller and shared Monitor worker health |

Task details include research entry points, current focus, local plan excerpts,
original problem status, assessment/Result references, and related Jobs. Only
Jobs owned by the current session have `/monitor job` links; other Jobs remain
visible as `Outside this session`. Shared
problems appear once; relations reference their IDs. `closed` is labeled `Ended`,
which does not assert scientific success or task completion. Omitted context is
marked and `/research read <id>` opens the underlying record. Node counts do not
measure research progress. Reading these views never changes task focus or wakes
the model; there is no separate planning command.

Lists and run details accept `--limit <1–100>` and `--cursor <cursor>`. A returned
next-page command preserves the filter and page size. IDs belong to the attached
session; a missing or foreign ID produces an error. Task cancellation always
requires an explicit Job policy.

All commands call the canonical `monitor/overview`, `monitor/tasks`,
`monitor/task/read|pause|resume|cancel`, `monitor/jobs`, `monitor/job/read|cancel`,
`monitor/runs`, `monitor/run/read`, and `monitor/health` Host methods directly.
Queries do not send Agent input or call the model. Task controls read the current
revision and send a stable request identity; a revision conflict is displayed,
not silently retried. Monitor's previous status/list/enable/disable methods and
per-Job automatic-follow-up switches are removed.

Pausing a user task prevents new automatic progress without cancelling its running
Jobs. Chat Esc/`turn/interrupt` stops the current reply and suppresses automatic
restart. Esc inside a Monitor panel only closes that panel. Cancelling a Job and
closing a terminal are separate actions. `/resume` switches the chat session;
`/monitor task resume` resumes work inside the current session.

Job wake and user-notification channels have independent receipts, leases and
backoff. A wake is accepted input, not proof that analysis completed. Task Controller
rechecks durable task and Job state before continuing. The Agent must still inspect
results; Monitor does not publish scientific conclusions or edit Nodes.

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
