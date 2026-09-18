# Terminal

The TSPi terminal is Pi's native TUI attached to the installation Host. The
Host is the only session owner; the terminal and TS Phone are equal clients of
it. One Host can serve every project below the configured workspace root.

## Start the Host

Start the installation Host with systemd, then attach the TUI to a project:

```bash
systemctl --user start ts-app-server-tspi.service
./TSPi --workspace reaction-a
```

Use `systemctl --user stop|restart|status ts-app-server-tspi.service` to manage
the Host lifecycle.

The Host identity is kept at
`.pi/app-server-host/server-id`; its private Unix socket is
under `$XDG_RUNTIME_DIR/tspi/` (or the installation's configured runtime
directory).

## Sessions and controls

The TUI uses Pi's native session directory. Create, select, rename, and remove
sessions with the standard Pi commands. `--session-id <id>` attaches a precise
session; `--continue` selects the most recent session. Exiting the TUI detaches
only that client and leaves the App Server running.

Ctrl+C interrupts the current local turn. `/abort` requests an App Server abort
for the active agent run. A prompt is never resent automatically after a
disconnect; inspect the transcript before trying again.

## Phone access

TS Phone connects once to this Host through Pi Radius using protocol v8. It can
list or create projects and create or switch sessions without another service
per project. It does not connect to the terminal process and does not require
a local HTTP service,
bridge secret, reverse proxy, or `TSPhoneServer`/`TSPhoneCtl` binary.

The Host exposes `WorkspaceDirectory.list/create` for project selection and
creation. A new session is requested through `SessionManagement.create` with
`{ workspaceId }`; the Host resolves that name to the validated direct-child
workspace and records its cwd in the session summary.
The TS Phone client must advertise these services; an older Phone build that
only knows project/session listing will need a client update before it shows
the create actions.

Phone is an interactive Pi client, not a read-only projection. A Phone prompt
runs in the selected workspace on the App Server machine and has the same
`read`, `write`, `bash`, and package tool inventory as a terminal prompt in that
session. The client transport does not filter commands; normal Host account,
workspace, capability, and operating-system permissions still apply.

## Browser control

TS Web remains a read-only scientific projection by default. To control one
existing Pi session from a browser, start the optional loopback adapter while
the Host is running:

```bash
./TSPi --gateway --workspace reaction-a --session-id <session-id> \
  --port 8767 --auth-token '<private-token>'
```

The adapter exposes the versioned `tspi-session-control/1` request contract and
an SSE transcript stream. It attaches to the Host session and never starts a
second Worker. Phone clients should continue using Pi Radius directly.

## Troubleshooting

- `workspace is unavailable`: bootstrap the project, then ensure the Host
  service is running.
- `App Server is not running`: start the single Host service or command above.
- `another Root Agent already owns workspace`: use the existing Host; do not
  start a second Host for the installation.
- A changed App Server UUID means a different installation or workspace; update
  the phone connection deliberately.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
storage, runtime, and recovery details.
