# TS Web ResearchMap Contract

TSPi owns the read-only ResearchMap provider. An optional `ts-web` client under
`components/ts-web/` consumes the canonical map payload without importing TSPi
Python modules. The map schema is `research-map/1`.

The request contract carries workspace identity and an optional map revision.
A response contains `workspace` metadata and the canonical `map`, or an
unchanged response with only revision metadata.
Errors and stale client state are transport conditions; they must not be
treated as scientific changes.

`source_root` and physical filesystem paths are private provider state and are
excluded from the public contract. Logical artifact paths remain bounded and
workspace-relative where the existing file locator requires them.

The provider transport uses `provider-request.schema.json` and
`provider-response.schema.json`. The independently released Web archive uses
`component-manifest.schema.json`; the suite manifest records the same protocol
set and installs the archive under `current/web/`.
