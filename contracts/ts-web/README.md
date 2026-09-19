# TS Web ResearchMap Contract

TSPi owns the read-only ResearchMap provider. An optional `ts-web` client under
`components/ts-web/` consumes the canonical map payload without importing TSPi
Python modules. The map schema is `research-map/1`.

Requests and responses use the `research-map-provider/1` JSON-lines protocol.
The `/map` route returns workspace metadata and the current
`ResearchMap.to_dict()` value. The transport does not define a Web projection
or an incremental snapshot model.

`source_root` and physical filesystem paths are private provider state and are
excluded from the public contract. Logical artifact paths remain bounded and
workspace-relative where the existing file locator requires them.

The provider transport uses `provider-request.schema.json` and
`provider-response.schema.json`. `research-map-response.schema.json` describes
the `/map` response envelope while the Python ResearchMap model owns the domain
invariants. The independently released Web archive uses
`component-manifest.schema.json`.
