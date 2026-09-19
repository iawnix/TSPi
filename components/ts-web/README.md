# TS Web Component

`@iawnix/ts-web` is an optional, read-only browser client for TSPi. It owns
the HTTP transport, browser assets, workspace registry commands, and the
ResearchMap client. It does not import `ts_agent` or own scientific state.

The component talks to the TSPi Agent through the versioned
`research-map-provider/1` JSON-lines protocol. TSPi keeps physical workspace
locations and loads the canonical ResearchMap. The Web response contains
canonical workspace data only.

The component is released as a self-contained archive with a manifest. A TSPi
Package may omit it; when selected, the installer places it under
`current/web/` and creates the `TSWeb` launcher.
The server binds to `127.0.0.1` by default. Binding a LAN or public address
requires the explicit `--allow-remote` flag and a token supplied with
`--auth-token-file` (recommended), `--auth-token`, or `TSPI_WEB_AUTH_TOKEN`;
use TLS when crossing an untrusted network. Token files must be absolute,
user-owned `0600` regular files without symbolic or hard links.
When a token is enabled, the browser prompts for it on first access and retains
it only in the current page's memory. Reloading or closing the page requires the
token again; it is never placed in the URL or persistent browser storage.
