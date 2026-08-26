# Workspace Contract

## Contents

- [Canonical Files](#canonical-files)
- [Bootstrap](#bootstrap)
- [Write Boundary](#write-boundary)
- [Identity And Paths](#identity-and-paths)
- [Integrity Invariants](#integrity-invariants)
- [Operational State](#operational-state)

## Canonical Files

A workspace stores scientific state in:

```text
workspace.json
research_state.json
phases.json
claims.json
claim_relations.json
research_nodes.json
observations.json
validation_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

`research_state.json` contains focus Claim/Node refs and immutable acceptance
history refs; it is not a workflow router. Current acceptance is derived rather
than stored as a permanent Claim flag. `phases.json` groups Nodes for human
navigation and carries no lifecycle or policy. ResearchNode artifacts live below
`nodes/<node_id>/`. Reports and operational records are not canonical science.

## Bootstrap

TSPi bootstraps before starting the Root Agent:

- a fresh workspace receives all canonical documents and required directories once;
- a complete workspace is validated without canonical rewrites;
- partial, invalid, symlinked, or unsupported canonical state fails closed.

Bootstrap does not rewrite unsupported state. Begin a distinct workspace when
the existing layout does not satisfy the active contract.

## Write Boundary

Only `ts_workspace_decision_apply` writes canonical state after bootstrap.
Normal callers use:

```text
context -> draft -> validate -> apply
```

Do not edit canonical JSON, JSONL, acceptance files, or `.agents` identity by
hand. Do not use Compute, Review, Report, UI, or remote tools as alternate
writers.

## Identity And Paths

The workspace has one immutable installation-derived identity. The Kernel owns
scientific record IDs and Node artifact roots. Public calls use logical IDs,
not constructed paths. Artifact catalog entries bind logical `art_...` IDs to
workspace-relative regular files and SHA-256 values.

Reject absolute artifact refs, traversal, symlink components, duplicate IDs,
digest mismatch, unknown owners, and files outside the workspace. Remote paths
are execution mirrors and never become canonical local refs.

## Integrity Invariants

- ClaimRelation and ResearchNode dependency graphs are acyclic.
- Every ResearchNode references one existing ResearchPhase; a primary Claim,
  when present, is included in the Node Claim scope.
- Every ref resolves to exactly one record of the expected kind.
- An open ResearchNode has no terminal result; a terminal Node has one.
- Activity request/status bindings, IDs, physical ownership, `node_refs`, and
  terminal status/result combinations are consistent.
- A ResearchNode cannot complete with a non-terminal owned Compute run,
  running/pending activities, or pending/unresolved compute controls. Failed
  activities require a non-success Node outcome.
- Every Observation and Finding is indexed by its producing/referenced Nodes.
- Observation datatype matches its value and artifact digests match files.
- Every GateSpec is content- and registry-digest bound.
- Every ValidationResult recomputes exactly from its GateSpec and selected
  Observations.
- Acceptance history snapshots a supported Claim, at least one GateSpec, the
  latest passing results, and applicable Findings. A shared projection marks a
  record current only while those inputs still match canonical state.
- Focus refs and acceptance indexes match existing canonical records.
- Decision replay is idempotent only for identical content.
- One Decision creates at most one Phase, starts at most one ResearchNode, and
  completes at most one ResearchNode. Starting and completing that same Node is
  valid; closing an existing Node and opening its successor in the same
  transaction requires the successor to depend explicitly on the completed Node.

## Operational State

Calculation intents and attempts, remote guards/receipts, activity journals,
Review runs/dispositions, report packages, notifications, Pi conversations,
locks, and UI state are operational or derived. They may be cited as provenance
only after verified primary artifacts are recorded as semantic Observations.

New operational ownership is explicit:

```text
nodes/<node_id>/attempts/<calc_id>/runs/<sub_id>/  Compute
reviews/<claim_id>/runs/<sub_id>/                Review
nodes/<node_id>/activities/<op_id>/                deterministic tools
operations/activities/<op_id>/                   workspace-level deterministic tools
```

`calc_n`, `sub_n`, and `op_n` are global workspace ordinals used for lookup,
not scientific meaning. Canonical Claims and Observations remain single
registries; the Web/locator derives their Claim-Node-Attempt neighborhood instead
of duplicating records into operational directories.

`TS Activity` is transient presentation state. The Activity Journal, Review
history, and compute controls are durable but do not mutate Claims by
themselves.
