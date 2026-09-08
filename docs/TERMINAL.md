# Terminal Client

The terminal is a client of the same TSPi Host used by Phone. It does not run
an Agent, select a model provider, load research Skills, or write scientific
state. Pi's session JSONL remains under the workspace, with one Host Worker
holding the writer locks. TS Web continues to read the research view.

## Start

Configure and start the bundled Host with the installation's `TSPhoneServer`
entrypoint. Service startup is an operator action, not a side effect of opening
a terminal. Then run:

```sh
./TSPi
./TSPi --workspace ts_001
./TSPi --workspace ts_001 --session-id session_1
./TSPi --workspace ts_001 -c
```

The active Host Controller is selected first. With several offline sessions,
choose one, or use `-c` for the latest. Browsing and selecting do not start a
Worker. New project/conversation actions create only Host-managed metadata;
the first Controller activation bootstraps research deterministically.

The client reads the installation's private `.pi/ts-phone/server.env` without
executing it. Exported `TS_PHONE_HOST`, `TS_PHONE_PORT`, and `TS_PHONE_STATE_DIR`
take precedence. The Host must use the same settings. Only `127.0.0.1` or `::1`
is allowed. The token is read from `TS_PHONE_STATE_DIR/auth.token` and is never
printed or passed as a process argument. It does not read `~/.pi/agent`;
provider credentials stay with the Host Worker.

The launcher resolves the SDK and terminal components from the Node-based Pi
installation selected by `PI_BIN` (default `~/.npm-global/bin/pi`). Releases do
not rely on source-checkout `node_modules`, install npm packages on startup, or
copy credentials. Pi 0.83 and 0.85 renderer exports are supported. A standalone
Pi binary without the Node SDK requires a separate Node-based Pi installation.

## Controls

Enter sends; Shift+Enter inserts a line break using Pi's editor. Ctrl+K opens
the command selector, Ctrl+O opens conversations. Page Up/Down scroll within
the loaded page. Ctrl+T expands or collapses tool details. Escape closes a
selector. Ctrl+C, Ctrl+D, and `/quit` detach, never terminate the Worker.

| Command | Effect |
| --- | --- |
| `/projects`, `/sessions` | Browse existing projects and conversations |
| `/new` | Name a new conversation in this project |
| `/continue` | Start or join this conversation without sending the draft |
| `/model` | Choose a model for a ready, idle Host Controller |
| `/abort` | Stop the exact displayed generation; remote jobs are unchanged |
| `/refresh`, `/latest` | Reload the latest bounded history and reconnect |
| `/start`, `/older`, `/newer` | Seek to the beginning or page through history |
| `/approvals` | Read and answer unexpired structured confirmation requests |
| `/receipt` | Reconcile an unconfirmed message, without resending it |

If a different idle Host Worker owns the workspace, `/continue` asks for an
explicit switch bound to that Worker's session revision. Busy, uncertain, or
external processes are not stopped. An external/native Pi process cannot be
adopted: exit it normally, then select its unchanged history in Host.

## Delivery And Recovery

Every prompt has a client message ID and session revision. Host validates and
deduplicates it before dispatching through Pi RPC. Client kind is display
metadata only; `terminal` never grants more authority than `phone`.

The terminal retains drafts on rejection. A lost HTTP receipt leaves the
message unconfirmed and prevents another send from that conversation in this
client. `/receipt` can confirm acceptance or rejection. Missing receipts,
expired journals, and changed Host generations mean **unknown**, not "not sent."
Reconnect reloads a snapshot and resumes SSE from its checkpoint; it never
replays commands. Drafts and pending client state are in memory, not another
conversation database. After closing with an unknown receipt, inspect the
canonical history and Host state before re-entering the message.

Host receipts are currently in-memory and bounded. This is not a durable
exactly-once delivery guarantee across Host restart. Terminal disconnect,
generation abort, Worker shutdown, and cancellation of a remote calculation
are separate operations.

## Native Pi Boundary

`--phone` aliases the thin client; it no longer starts a second interactive Pi.
Use `--standalone` for native Pi arguments, native slash commands, extension
dialogs/widgets, shell integration, or batch/RPC modes. The thin client has
text input, Markdown, tool summaries, model/context status, and explicit Host
commands. It does not serialize arbitrary native TUI components, load local
Skills, or forward unknown slash commands. The Host's Controller/Observer
policy and the Python research kernel are unchanged.

## Maintainer Checks

```sh
npm run test:terminal
TS_PHONE_SOURCE=/path/to/ts-phone npm run test:terminal-host
```

The integration check uses a temporary Host, a fake Worker, two terminal
controllers, a Phone request, and a real PTY. It verifies one Worker, offline
browsing, input receipts, resizing and detach. It does not call a provider or
touch installed research workspaces. Run the Phone server tests and the
wheel-backed launcher/session-guard tests before delivering a unified package.
