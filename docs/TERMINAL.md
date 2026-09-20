# Terminal

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

The TSPi terminal is Pi's native TUI attached to the installation Host. The
Host is the only session owner; the terminal and TS Phone are equal clients of
it. One Host can serve every project below the configured workspace root.

## Open a workspace

Connect to a project directly. If the Host is not running, TSPi starts the one
installation-wide service selected during installation (user or system scope)
and waits for its Unix socket before attaching the TUI:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

Use `systemctl --user stop|restart|status ts-app-server-tspi.service` for a
user-scoped installation, or omit `--user` for a system-scoped installation.
With service scope `none`, the managed Host is disabled and `--standalone` is
reserved for development or recovery.

The Host identity is kept at
`.pi/app-server-host/server-id`; its private Unix socket is
under `$XDG_RUNTIME_DIR/tspi/` (or the installation's configured runtime
directory).

## Sessions and controls

With no session option, TSPi creates a new conversation. `-c` or `--continue`
selects the latest conversation in the current workspace; `--session-id <id>`
attaches a precise conversation in that workspace. The TUI uses Pi's native
session directory. Exiting it detaches only that client and leaves the App
Server running.

Ctrl+C interrupts the current local turn. `/abort` requests an App Server abort
for the active agent run. A prompt is never resent automatically after a
disconnect; inspect the transcript before trying again.

## Phone access

TS Phone connects to this Host through TSPi Link. Both the Phone and Host open
outbound WSS connections to the configured TSPi Relay, so the App Server does
not expose an inbound public port. The Relay authorizes devices and forwards
opaque App Server bytes; it does not own projects, sessions, or transcripts.

Create a five-minute, single-use pairing code on the Host:

```bash
./TSPi phone pair
```

Enter the printed Relay URL and code in TS Phone. Use `./TSPi phone devices`
to list authorized devices and `./TSPi phone revoke <device-id>` to revoke one.
The Phone can then list or create projects and create or switch sessions. It
does not connect to the terminal process or require a per-project service.

The Host exposes `WorkspaceDirectory.list/create` for project selection and
creation. A new session is requested through `SessionManagement.create` with
`{ workspaceId }`; the Host resolves that name to the validated direct-child
workspace and records its cwd in the session summary.
The TS Phone client must advertise these services; an older Phone build that
only knows project/session listing will need a client update before it shows
the create actions.

Phone is an interactive Pi client, not merely a viewer. A Phone prompt
runs in the selected workspace on the App Server machine and has the same
`read`, `write`, `bash`, and package tool inventory as a terminal prompt in that
session. The client transport does not filter commands; normal Host account,
workspace, capability, and operating-system permissions still apply.

## Browser control

TS Web remains a read-only browser of the canonical ResearchMap by default. To control one
existing Pi session from a browser, start the optional loopback adapter while
the Host is running:

```bash
./TSPi --gateway --workspace reaction-a --session-id <session-id> \
  --port 8767 --auth-token '<private-token>'
```

The adapter exposes the versioned `tspi-session-control/1` request contract and
an SSE transcript stream. It attaches to the Host session and never starts a
second Worker. Phone clients use TSPi Link directly.

## Troubleshooting

- `workspace is unavailable`: inspect the workspace name and configured workspace root.
- `could not start ts-app-server-tspi.service`: inspect the configured service
  with `systemctl --user status` (user scope) or `systemctl status` (system scope).
- `another Root Agent already owns workspace`: use the existing Host; do not
  start a second Host for the installation.
- `TSPi Link is not configured`: enroll the Host with the installer before
  creating a Phone pairing.
- A changed Host UUID means a different installation; pair the phone again.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
storage, runtime, and recovery details.
