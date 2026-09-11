# TS Web Projection Contract

TSPi owns the read-only projection provider. An optional `ts-web` client under
`components/ts-web/` consumes the snapshot and graph payloads without importing
TSPi Python modules.
The current compatibility baseline is `ts-web-workspace/6` and
`ts-explorer-graph/6`.

The request contract carries workspace identity and the two independent
revision values. A response is either a changed snapshot with `workspace`,
`view`, and `graph`, or an unchanged snapshot with only revision metadata.
Errors and stale client state are transport conditions; they must not be
treated as scientific changes.

`source_root` and physical filesystem paths are private provider state and are
excluded from the public contract. Logical artifact paths remain bounded and
workspace-relative where the existing file locator requires them.

The provider transport uses `provider-request.schema.json` and
`provider-response.schema.json`. The independently released Web archive uses
`component-manifest.schema.json`; the suite manifest records the same protocol
set and installs the archive under `current/web/`.
