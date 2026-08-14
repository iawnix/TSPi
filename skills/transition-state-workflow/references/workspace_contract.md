# Workspace Contract

## Canonical Files

A v3 workspace stores scientific state in:

- `research_state.json`: Node index, parent edges, open Nodes, accepted refs,
  and provenance;
- `claims.json`: Claims and focus Claim refs;
- `evidence.json`: immutable Evidence records and lifecycle events;
- `gate_results.json`: deterministic Gate results;
- `nodes/<node_id>/node.json`: complete Node record;
- `accepted/<acceptance_id>.json`: policy-bound accepted Claim artifact;
- `decisions/`, `decision_log.jsonl`, and `transaction_log.jsonl`: mutation
  audit trail.

Reports, calculations, agent journals, remote receipts, and notifications are
not canonical scientific state.

## Write Boundary

Only the workspace Kernel writes canonical files. Every mutation after initial
bootstrap must use `ts-decision/3`, match the invoked action, bind the current
report and base revision, and pass a complete post-mutation dry run.

A decision ID is idempotent only when its complete content matches a committed
transaction. Reusing the ID for different content or encountering an incomplete
transaction fails closed.

Transaction order is prepare record, immutable decision snapshot, proposed file
writes, decision log, then committed record. Apply holds the workspace lock and
repeats validation.

## Integrity Invariants

- Node IDs, Claim IDs, Evidence IDs, Gate-result IDs, and accepted refs are
  unique and resolvable.
- Parent edges match the corresponding Node records and contain no cycles.
- Every Evidence artifact path remains inside the workspace and under an
  allowed owner location.
- Evidence lifecycle events refer to existing Evidence and preserve history.
- Gate results cite active Evidence and reproduce the current deterministic
  policy result.
- Claim histories cite existing Nodes, Evidence, and Gate results.
- Accepted artifacts cite one Claim and the passing Gate set required by their
  named audit policy.
- Operational journals cannot appear in scientific evidence registries.

A successful Review creates an operational obligation for one write-once Root
response. A pending response may block a later scientific mutation, but the
response never becomes Evidence or a Gate result.

## Migration

Runtime accepts v3 only. Convert an old workspace through the explicit
`scripts/migrate_workspace_v2_to_v3.py` copy migration, validate the destination,
and retain the source unchanged. Do not add compatibility fields or aliases to
normal reads and writes.
