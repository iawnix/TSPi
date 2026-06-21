# Workspace Contract

The workspace root is the only trusted state source.

Required files:

- `manifest.json`
- `tree.json`
- `mechanism_model.json`
- `pathway_model.json`
- `evidence_registry.json`
- `knowledge_base.md`
- `decision_log.jsonl`

Required directories:

- `inputs/`
- `nodes/`
- `reports/`
- `accepted/`
- `rejected/`

Only `ts_workspace` may write root ledgers. Backends, remote helpers,
molecular comparison, web views, and final reports must return artifacts or
read models instead of mutating the workspace.

Node-scoped artifacts belong under:

```text
nodes/<node_id>/inputs/
nodes/<node_id>/outputs/
nodes/<node_id>/scratch/
nodes/<node_id>/remote/
```

Fresh endpoint-based searches should create an explicit `n000` node through
`start_node` after `init_workspace`. Use `phase=endpoint` or `phase=preflight`
and close it after endpoint provenance, charge/multiplicity, atom-order
mapping, source hashes, and initial reaction-center checks are recorded.
Candidate generation should then start at `n001` with `parent_node=n000`.
Legacy workspaces without `n000` remain valid.

The workspace validator checks required files, node JSON records, current focus,
append-only evidence identity, and forbidden public fields.
