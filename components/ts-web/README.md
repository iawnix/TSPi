# TS Web Component

`@iawnix/ts-web` is an optional, read-only browser client for TSPi. It owns
the HTTP transport, browser assets, workspace registry commands, and the
projection client. It does not import `ts_agent` or own scientific state.

The component talks to the TSPi Agent through the versioned
`ts-web-provider/1` JSON-lines protocol. TSPi keeps physical workspace
locations and evaluates the projection. The Web response contains logical
workspace data only.

The component is released as a self-contained archive with a manifest. A TSPi
Package may omit it; when selected, the installer places it under
`current/web/` and creates the `TSWeb` launcher.
The server binds to `127.0.0.1` by default. Binding a LAN or public address
requires the explicit `--allow-remote` flag and a token supplied with
`--auth-token` or `TSPI_WEB_AUTH_TOKEN`; use TLS when crossing an untrusted
network.
