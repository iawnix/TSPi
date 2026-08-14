# State Model

Workspace v3 separates scientific meaning from operational execution.

## Node

A `ts-node/3` record is one bounded research act. It stores:

- `node_id` and one optional `parent_node`;
- a Root-selected `objective`;
- descriptive `tags`;
- Claim, operation, Evidence, and Gate-result refs;
- open/closed/stopped state and an optional terminal result.

Node tags do not authorize operations or determine what may follow. A child may
represent a retry investigation, a new method, an alternative Claim, an audit,
or any other bounded act selected by the Root Agent.

## Claim

A Claim is a versioned scientific statement with a free versioned `kind`, text,
optional parent Claim, required Gate names, supporting refs, current status, and
append-only history. The Root Agent creates Claims and supplies every status
update. The Kernel validates cited facts and Gate results; it does not infer a
Claim update from a program outcome.

## Evidence

A `ts-evidence/2` record stores immutable facts, a free versioned `kind`, a
source tier, artifact refs, and provenance. Evidence has no workflow role or
layer. Use `supersedes_evidence_id` for a corrected record, or append a
withdrawn/invalidated Evidence event while retaining audit history.

## Gate

A `ts-gate-result/1` record is the output of a named fact policy. It binds one
or more active Evidence refs, a target ref, a policy version, a deterministic
verdict, and diagnostics. Gates protect declared scientific checks and
acceptance policies; they do not update Claims or choose later Nodes.

## Scientific And Operational Revisions

Canonical files determine `workspace_revision`. Calculation attempts, remote
controls, child-agent journals, notifications, and UI state determine
`operational_revision` only. An operational success or failure cannot silently
change scientific state.

Use `report_node` for one bounded history capsule and
`report_lineage_context` for a read-only ancestor/delta comparison. Both are
views; the Root Agent remains the only research-path authority.
