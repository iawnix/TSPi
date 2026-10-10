# CoRAgent Web Component

`@iawnix/coragent-web` is an optional, read-only browser client for CoRAgent. It owns
the HTTP transport, browser assets, workspace registry commands, and the
Research memory client. It does not import `research_agent.application` or own scientific state.

The component talks to the CoRAgent Agent through the versioned
`research-memory-provider/1` JSON-lines protocol. CoRAgent keeps physical workspace
locations and loads the canonical Research memory. The Web response contains
canonical workspace data only.

The component is released as a self-contained archive with a manifest. A CoRAgent
Package may omit it; when selected, the installer places it under
`current/web/` and creates the `coragent-web` launcher.
The server binds to `127.0.0.1` by default. Binding a LAN or public address
requires the explicit `--allow-remote` flag and a token supplied with
`--auth-token-file` (recommended), `--auth-token`, or `CORAGENT_WEB_AUTH_TOKEN`;
use TLS when crossing an untrusted network. Token files must be absolute,
user-owned `0600` regular files without symbolic or hard links.
When a token is enabled, the browser prompts for it on first access and retains
it only in the current page's memory. Reloading or closing the page requires the
token again; it is never placed in the URL or persistent browser storage.
