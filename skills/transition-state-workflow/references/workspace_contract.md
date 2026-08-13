# Workspace Contract

The workspace root is the only trusted research-state source.

Canonical files:

- `research_state.json`: nodes, edges, branch events, focus, and accepted refs.
- `hypotheses.json`: hypotheses, predictions, accepted facts, pathways, and open
  questions.
- `evidence_registry.json`: evidence identity, role, quality, paths, and
  provenance.

`decision_log.jsonl` and `transaction_log.jsonl` are audit logs. Reports,
Markdown summaries, and web payloads are derived views.

Only `ts_workspace` may mutate canonical files. Backends, remote helpers,
renderers, web views, report builders, and child agents return artifacts or read
models.

## Directories

```text
inputs/
nodes/
reports/
accepted/
rejected/
decisions/
```

New node calculations use:

```text
nodes/<node>/attempts/<intent>/
├── intent.json
├── prepared.json
├── status.json
└── outputs/
```

Node-level inputs, non-calculation outputs, scratch, and remote folders may
also exist. Attempt records are operational artifacts, not a fourth
canonical state file.

## Decisions And Transactions

Every applied decision is copied to `decisions/<decision_id>.json`. Reusing an
ID is a no-op only when content is identical and the transaction is already
committed. Different content or an incomplete prior transaction is rejected.
`decision_id` is a bounded path-safe identifier. `report_id` is
`rep_<workspace_revision prefix>`, so repeated reports of unchanged scientific
state have one stable identity.

Mutation order:

1. stage the full decision snapshot, proposed state, and next decision log;
2. record intended paths plus staged and pre-mutation SHA-256 values in a
   `transaction_log.jsonl` `prepare` row;
3. move existing targets to transaction-local backups and replace each target
   from staging;
4. append transaction `committed`;
5. remove staging and backups only after commit is recorded.

If replacement fails, the engine verifies hashes, restores every backup, removes
new staged targets, and appends `aborted`. A later mutation performs the same
recovery for an interrupted `prepare` before evaluating a new decision. Legacy
prepare rows without complete recovery metadata, unsafe paths, missing backups,
or externally changed targets are not guessed: mutation stops and preserves
`.ts-transactions/<decision_id>/` for manual reconciliation.

An unmatched prepare row or malformed transaction log is a workspace validation
error. This mechanism provides a recoverable consistent multi-file commit; it
does not claim that the filesystem replaces all files in one atomic operation.

`init_workspace --force` is destructive and requires an explicit auditable
decision. Old workspace layouts are not migrated by this package.

## New Research Contract

- `n000` is `node_type=intake`.
- The first mechanism hypothesis is created by a
  `mechanism, mechanism_action=propose` node.
- Candidate, validation, audit, and later mechanism nodes reference a known
  hypothesis.
- Validation predictions declare a matching `validation_scope`.
- Every post-`n000` node records branch context.
- Candidate and validation closures cannot set hypothesis or audit status.
- Mechanism closures cannot set audit status.
- Audit closures cannot create a hypothesis verdict.

Every node must conform to `ts-node/2`.

For `new_solution_branch`, `solution_ref.solution_id` is unique within its
hypothesis across the workspace. If the source has a solution identity,
`parent_solution_id` must cite it. For `new_pathway_branch`, `pathway_id` must be
new across declared pathways and prior branch nodes, and the hypothesis cannot
change. Node, tree entry, and branch-event target refs must agree.

Historical closed `new_solution_branch` nodes created by the prior engine without
this identity may be corrected only through `update_workspace.repair_solution_ref`.
The repair refuses running nodes, overwrites, and duplicate identities; it updates
the node, tree entry, and branch event together and appends `lineage_repairs`
audit metadata.

## Evidence

Evidence role is extensible, but built-in consumers recognize roles including:

- intake and endpoint provenance, mapping, charge, and multiplicity;
- candidate geometry and endpoint-conformer selection;
- `tsfreq_gate` and mode assignment;
- connectivity and IRC endpoint assignment;
- stereochemical connectivity when declared;
- endpoint/intermediate identity;
- electronic-structure and state-character diagnostics;
- shared-basin consistency;
- accepted-TS audit;
- pathway audit summary;
- previous attempt summary.

Path-bearing evidence must point to an artifact owned by the current node or
attempt. If an upstream artifact is consumed, write a current-node validation
artifact and preserve the upstream ref in provenance.

For a pathway audit, register an evidence record before closure whose quality
contains `quality.strict_pathway_decision=accepted` or
`quality.strict_pathway_decision=pathway_not_accepted`.

Evidence registration does not itself set hypothesis or audit status. The Root
Agent opens the appropriate mechanism or audit node.

Evidence history is append-only. To replace an incomplete or incorrectly owned
record, append a new evidence record with
`supersedes_evidence_id=<old_evidence_id>`. To retain a record in history while
removing it from the current evidence view, append an `evidence_lifecycle`
record with `role=evidence_lifecycle`,
`lifecycle_status=withdrawn|invalidated`, and
`supersedes_evidence_id=<target_evidence_id>`. Targets must be earlier active
records. Validators, scientific gates, and default reports consume active
evidence only; references to superseded evidence resolve to the active
replacement. Withdrawn and invalidated references resolve to no current
evidence and therefore cannot satisfy a gate.

## Recalculation And Retries

- Technical retry: another attempt under the same node with
  `attempt_kind=retry`.
- Scientific recalculation: a new node with `attempt_kind=recalculation`, a
  source ref, changed settings, and `relation=recalculation_of`.

Remote paths declare `authority=execution_mirror`; only collected local
artifacts may become evidence.

## Validation

Workspace validation checks:

- required files and JSON schemas;
- node identity, lifecycle, type/scope, and allowed closure status axes;
- references to nodes, hypotheses, predictions, pathways, evidence, and
  artifacts;
- branch ancestry and recalculation source consistency;
- evidence ownership and gate structure;
- accepted-TS and pathway-audit prerequisites;
- transaction completeness and decision snapshots.

Warnings expose suspicious but recoverable state. Validators do not choose the
next branch, retry, hypothesis, or stop decision.

`validate_decision` explicitly previews the same mutation and finalizer path as
apply against an isolated temporary workspace copy. Apply does not trust an old
preview: while holding the workspace lock it checks revision/report identity and
runs the complete dry run again before writing. A successful preflight therefore
covers finalizer-only evidence gates while leaving the source workspace
unchanged, but only apply decides whether the live mutation can proceed.
