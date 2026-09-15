# Terminal

The TSPi terminal is Pi's native TUI attached to a workspace App Server. The
App Server is the only session owner; the terminal and TS Phone are equal
clients of it.

## Start a workspace

From the installation directory:

```bash
./TSPi --app-server --workspace reaction-a
```

Leave that process running, then in another terminal attach the TUI:

```bash
./TSPi --workspace reaction-a
```

If a systemd template was enabled by the installer, start the instance with:

```bash
systemctl --user start 'ts-app-server-tspi@reaction-a.service'
```

The App Server identity is kept at
`workspaces/reaction-a/.pi/app-server/server-id`; its private Unix socket is
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

TS Phone connects to this same App Server through Pi Radius using protocol v8.
It does not connect to the terminal process and does not require a local HTTP
service, bridge secret, reverse proxy, or `TSPhoneServer`/`TSPhoneCtl` binary.

## Troubleshooting

- `workspace is unavailable`: create it once with `TSPi --app-server --workspace <name>`.
- `App Server is not running`: start the matching systemd instance or command above.
- `another Root Agent already owns workspace`: use the existing App Server; do
  not start a second one for the same workspace.
- A changed App Server UUID means a different installation or workspace; update
  the phone connection deliberately.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
storage, runtime, and recovery details.
