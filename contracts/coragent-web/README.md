# CoRAgent Web Research Memory Contract

CoRAgent owns the read-only Research Memory provider. The optional `coragent-web` client consumes `research-memory-provider/1` JSON-lines responses without importing private CoRAgent modules or maintaining another research database. The Agent bridge injects runtime-owned Job facts; the Memory package does not import the execution adapter.

| Route | Response |
| --- | --- |
| `snapshot` | Workspace metadata and a bounded `research-snapshot/3` context |
| `nodes` | Searchable, paginated Node list |
| `records` | Search across Nodes, Results and historical records |
| `record/<ref>` | Exact Node, Result or record detail, with bounded text pages |
| `artifact/<id>` | Artifact manifest and a bounded content preview |

The snapshot response uses `research-memory-response/1`. It contains original requirements, selected research Nodes, assessments, related result summaries, execution events, running/uncollected Jobs and explicit routes for omitted content. There is no Agent-maintained global progress object.

A Node detail supplies its current problem, hypothesis or approach, plan, progress, selected assessment, explicit relations, Results, review notices and Job associations. Links navigate the research map; Result inputs continue to reference specific immutable versions. A newer result does not silently replace a downstream input or prove scientific validity.

`nodes` supports query, offset and limit. `records` supports query, origin, node_id, kind, after_sequence, offset and limit. `record/<ref>` uses offset and limit measured in Unicode characters; follow next_offset. Artifact preview offsets count bytes and text decoding can replace non-text bytes. Reading and navigation do not create evidence dependencies.

`source_root` and physical workspace paths remain private provider state. Transport envelopes use `provider-request.schema.json` and `provider-response.schema.json`. The snapshot schema and fixture are `research-memory-response.schema.json` and `research-memory-response.fixture.json`. Independently released Web archives declare provider, snapshot and theme versions in `component-manifest.schema.json`. Removed notebook/global-progress protocols have no compatibility reader.
