# Terminal

The TSPi terminal is Pi's native TUI attached to the installation Host. The
Host is the only session owner; the terminal and TS Phone are equal clients of
it. One Host can serve every project below `workspaces/`.

## Start the Host

From the installation directory:

```bash
./TSPi --host
```

Leave that process running, then in another terminal attach the TUI to a project:

```bash
./TSPi --workspace reaction-a
```

If the Host service was enabled by the installer, start it with:

```bash
systemctl --user start ts-app-server-tspi.service
```

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
list projects and switch sessions without another service per project. It does
not connect to the terminal process and does not require a local HTTP service,
bridge secret, reverse proxy, or `TSPhoneServer`/`TSPhoneCtl` binary.

## Troubleshooting

- `workspace is unavailable`: bootstrap the project, then ensure `TSPi --host`
  is running.
- `App Server is not running`: start the single Host service or command above.
- `another Root Agent already owns workspace`: use the existing Host; do not
  start a second Host for the installation.
- A changed App Server UUID means a different installation or workspace; update
  the phone connection deliberately.

See [Architecture](ARCHITECTURE.md) and [Installation](INSTALLATION.md) for
storage, runtime, and recovery details.
