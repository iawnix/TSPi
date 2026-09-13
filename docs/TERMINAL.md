# Terminal Client

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

## Start

The terminal and TS Phone connect to the same Host conversation. The Host runs
Pi Workers and stores their sessions under the research workspace.

Start the installed Phone service, then open a terminal:

```bash
systemctl --user start ts-phone-tspi.service
cd /path/to/TSPi-installation
./TSPi
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --session-id <session-id>
```

Use the service command when installation configured a systemd user service.
For manual startup, run `./TSPhoneServer`; see
[Phone configuration](INSTALLATION.md#configure-ts-phone).

The client selects the active Host Controller first. Choose from existing
conversations, use `--continue` for the latest, or provide an exact session ID.
Opening history reads the conversation. Sending a message creates a queued
request and starts research when the workspace is available.

## Configuration

The client reads `.pi/ts-phone/server.env`. Exported `TS_PHONE_HOST`,
`TS_PHONE_PORT`, and `TS_PHONE_STATE_DIR` override file settings.
`TSPhoneServer` and `TSPhoneCtl` use the same configuration reader.

Terminal connections use `127.0.0.1` or `::1`; authentication reads
`TS_PHONE_STATE_DIR/auth.token` privately. Pi model credentials remain in
the Worker's configured Pi directory.

The launcher selects a Node-based Pi installation through `PI_BIN`, or the
first `pi` on `PATH`. It loads the terminal components from that
installation's SDK. Pi 0.83 and 0.85 renderer exports are supported.
When using a standalone Pi binary, configure a Node-based installation for
the shared terminal.

## Controls

Enter sends; Shift+Enter inserts a line break. Ctrl+K opens commands and Ctrl+O
opens conversations. Page Up/Down scroll the loaded page. Ctrl+T expands tool
details; Escape closes a selector. Ctrl+C, Ctrl+D, and `/quit` detach the terminal,
and the Host Worker continues.

| Command | Action |
| --- | --- |
| `/projects`, `/sessions` | Browse projects and conversations |
| `/new` | Create a conversation in this project |
| `/continue` | Refresh the conversation; Hosts without queues activate its Worker |
| `/model` | Select the model for future messages |
| `/queue` | Inspect requests, cancel waiting work, or acknowledge an inspected uncertain outcome |
| `/abort` | Stop the displayed generation; cancel remote calculations through their own tools |
| `/refresh`, `/latest` | Load the latest history and reconnect |
| `/start`, `/older`, `/newer` | Navigate history pages |
| `/approvals` | View and answer current confirmation requests |
| `/receipt` | Check an unconfirmed message's delivery |

With `command.queue`, several clients can view and enqueue work while the Host
runs one turn per workspace. To continue a native/external Pi session in Host,
exit that process normally and open its history. Hosts without queues use
explicit switching while the Worker is idle.

## Delivery And Recovery

Each prompt carries a client message ID and session revision. The Host
validates and deduplicates the request before Pi RPC dispatch. Rejected sends
keep their draft.

After a lost HTTP reply, use `/receipt` to check delivery. If the receipt has
expired or the Host generation changed, inspect history and Host state before
re-entering the message. Drafts and pending client state last for the current
terminal process.

Queued requests and their selected models are persisted before acknowledgement.
A Host restart retains waiting requests and marks interrupted execution
`unknown`, pausing later work in that workspace. Inspect history and outputs,
stop the uncertain Worker, then acknowledge the outcome through `/queue`.
Model-service failures produce failed receipts when retries are exhausted.
Completed tool actions remain recorded after generation stops.

Direct receipts and event delivery history are bounded in-memory records.
On reconnect, SSE resumes from a checkpoint or sends a current snapshot if the
cursor is too old. The client refreshes its view from that snapshot.

Terminal disconnect, generation abort, Worker shutdown, and remote calculation
cancellation have separate effects.

## Native Pi

Use `--standalone` for Pi's native slash commands, extension dialogs, widgets,
shell integration, and batch/RPC options:

```bash
./TSPi --standalone --workspace reaction-a
```

The shared terminal provides text input, Markdown, tool summaries, model/context
status, and the Host commands above. `--phone` selects this shared terminal.

## Maintainer Checks

```bash
npm run test:terminal
TS_PHONE_SOURCE=/path/to/ts-phone npm run test:terminal-host
```

The integration check uses a temporary Host, a fake Worker, two terminal
controllers, a Phone request, and a real PTY. It checks shared Worker use,
history browsing, receipts, resizing, and detach. Package validation also
includes Phone server and launcher/session-guard tests.
