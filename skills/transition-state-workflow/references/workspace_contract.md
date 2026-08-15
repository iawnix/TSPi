# Workspace Contract

## Canonical Files

A v4 workspace stores scientific state in:

```text
workspace.json
research_state.json
claims.json
claim_relations.json
research_acts.json
observations.json
validation_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

`research_state.json` contains focus Claim/Act refs and immutable acceptance
history refs; it is not a workflow router. Current acceptance is derived rather
than stored as a permanent Claim flag. ResearchAct artifacts live below
`acts/<act_id>/`. Reports and operational records are not canonical science.

## Bootstrap

TSPi bootstraps before starting the Root Agent:

- a fresh workspace receives all v4 documents and required directories once;
- a complete v4 workspace is validated without canonical rewrites;
- partial, invalid, symlinked, or legacy canonical state fails closed.

There is no legacy reader or migration command. Keep an older workspace with
its matching release or begin a distinct v4 workspace.

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
scientific record IDs and Act artifact roots. Public calls use logical IDs,
not constructed paths. Artifact catalog entries bind logical `art_...` IDs to
workspace-relative regular files and SHA-256 values.

Reject absolute artifact refs, traversal, symlink components, duplicate IDs,
digest mismatch, unknown owners, and files outside the workspace. Remote paths
are execution mirrors and never become canonical local refs.

## Integrity Invariants

- ClaimRelation and ResearchAct dependency graphs are acyclic.
- Every ref resolves to exactly one record of the expected kind.
- An open ResearchAct has no terminal result; a terminal Act has one.
- Every Observation and Finding is indexed by its producing/referenced Acts.
- Observation datatype matches its value and artifact digests match files.
- Every GateSpec is content- and registry-digest bound.
- Every ValidationResult recomputes exactly from its GateSpec and selected
  Observations.
- Acceptance history snapshots a supported Claim, at least one GateSpec, the
  latest passing results, and applicable Findings. A shared projection marks a
  record current only while those inputs still match canonical state.
- Focus refs and acceptance indexes match existing canonical records.
- Decision replay is idempotent only for identical content.

## Operational State

Calculation intents and attempts, remote guards/receipts, activity journals,
Review runs/dispositions, report packages, notifications, Pi conversations,
locks, and UI state are operational or derived. They may be cited as provenance
only after verified primary artifacts are recorded as semantic Observations.

`TS Activity` is transient. Review history and compute controls are durable but
do not mutate Claims by themselves.
