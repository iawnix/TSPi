# ChangeSet Contract

`research_change` is the only public mutation boundary for `ResearchMap`. It accepts
one object containing `rationale`, optional `basisRefs`, optional
`expectedRevision`, and a non-empty `operations` array. Query
`research_read mode=operations` for the current catalog before using an unfamiliar
operation.

## Operations

Each operation uses `type` and an explicit project-local `id` for objects it
creates. References use the IDs already present in the map.

| Type | Required data |
| --- | --- |
| `create_phase` | `id`, `title`; optional `objective` |
| `create_claim` | `id`, `statement`; optional `status`, `predictions`, `falsifiers` |
| `create_node` | `id`, `title`, `objective`; optional `phase_id`, `claim_ids`, `dependency_ids` |
| `create_finding` | `id`, `node_id`, `statement`, `kind` (`fact` or `issue`); fact fields are `value`, `datatype`, `unit`, `provenance`; issue fields are `status`, `severity`, `resolution` |
| `create_gate` | `id`, `scope` (`node` or `claim`), `target_id`, optional `criteria` |
| `evaluate_gate` | `gate_id`, `verdict`, optional `message`, `evidence_refs` |
| `set_node_state` | `node_id`, `state`; closing also needs `outcome` and `summary` |
| `set_claim_status` | `claim_id`, `status` |
| `relate_claims` | `source_id`, `target_id`, `relation` |
| `set_focus` | `claim_ids`, `node_ids` |

Object IDs must be unique within the map and references must resolve in the
proposed post-state. Operations run in order, so a later operation can refer to
an object created earlier in the same request. Keep one coherent research change in a
single ChangeSet; unrelated changes should use separate requests.

## Commit Rules

The Kernel locks the workspace, loads the current map, checks
`expected_revision` when present, applies operations to a detached copy, runs
the full map validator, increments `revision`, and replaces `research_map.json`
atomically. A rejected request does not alter the prior map. Do not edit the
JSON file, transaction log, or TS Web data directly.

`create_finding` records the Node's verified output. It is not a generic log
entry: use `FactFinding` for a value that supports a scientific statement and
`IssueFinding` for a limitation, anomaly, conflict, or unresolved question.
`create_gate` and `evaluate_gate` are the Gate lifecycle. Claim status and Gate
verdict are independent: a Gate evaluation does not silently change a Claim.
