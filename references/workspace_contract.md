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
- `decisions/`

`decisions/` holds one file per applied decision (`<decision_id>.json`) — the
full decision payload as submitted. `decision_log.jsonl` rows carry a
`snapshot_ref` pointing at the snapshot so audits and future replays can
recover the exact decision without depending on the log row alone. If a
snapshot file already exists, the same `decision_id` may be reused only for the
exact same decision content and an already committed transaction; the repeated
call is a no-op. Different content with the same `decision_id`, or a matching
snapshot without a committed transaction, is rejected before any state write.
`decisions/` is auto-created on first mutation, so an old workspace missing it
is a warning (`missing_soft_dir`), not an error.

`init_workspace` refuses to overwrite an already-initialized workspace by
default. Pass `force=True` (or `--force` on the CLI) to reinitialize; that is
destructive and removes workspace-owned state directories and root state files
before creating a fresh workspace. Force reinitialization requires an
`init_workspace` decision JSON so the destructive reset is auditable. Do not
use it on a research directory unless that reset is explicitly intended.

## Transaction Log

Every mutation is wrapped in a two-phase envelope written to
`transaction_log.jsonl`:

```
{"decision_id": "...", "stage": "prepare",   "action": "end_node", "paths": [...], ...}
{"decision_id": "...", "stage": "committed", "action": "end_node", "paths": [...], ...}
```

The flow inside `_commit_transaction`:

1. Append `prepare` row (lists every path this mutation will write).
2. Write `decisions/<decision_id>.json` first, so a crash after state writes
   still leaves the submitted decision available for audit.
3. Apply every proposed state write via `apply_change` (each write is already
   atomic per file: temp file + `fsync` + `rename`).
4. Append the `decision_log.jsonl` row with the decision snapshot ref and
   result summary.
5. Append `committed` row.

`validate_workspace` scans `transaction_log.jsonl` for any `prepare` row
without a matching `committed` row and reports it as
`pending_transaction` (warning). A workspace with a pending transaction is
still `valid=true` — the warning is a hint to inspect that decision's
snapshot and manually verify the listed state paths. Automatic reuse of the
same `decision_id` is blocked until the transaction is known to be committed,
because append-style mutations may not be safe to replay blindly.

Because writes 3 and 4 are sequential, a crash between them can leave state
files written but the decision_log row missing. The `pending_transaction`
warning is the recovery hook: `decisions/<decision_id>.json` is the source of
truth for what the mutation intended, and the state files are the source of
truth for what was written. If a `prepare`/`committed` transaction exists but
the decision snapshot is missing, automatic reuse of that `decision_id` is
rejected because append-style mutations may not be safe to replay blindly.

Only `ts_workspace` may write root state files. Backends, remote helpers,
structure analysis, web views, and final reports must return artifacts or
read models instead of mutating the workspace.

Node-scoped artifacts belong under:

```text
nodes/<node_id>/inputs/
nodes/<node_id>/outputs/
nodes/<node_id>/scratch/
nodes/<node_id>/remote/
```

## Strict Hypothesis Model

`init_workspace` creates:

```json
{
  "schema_version": "ts-mechanism",
  "focus_hypothesis_id": null,
  "hypotheses": [],
  "accepted_facts": [],
  "refuted_hypotheses": [],
  "open_questions": []
}
```

Fresh endpoint-based searches must create an explicit `n000` node through
`start_node` after `init_workspace`. Use `phase=endpoint`; this phase is
reserved for `n000`.
The `n000` decision must include `payload.initial_mechanism_hypothesis`.

Close `n000` after endpoint provenance, charge/multiplicity, atom-order
mapping, source hashes, reaction-center delta, and initial mechanism evidence
are recorded. Candidate generation starts at `n001` with `parent_node=n000` and
`payload.hypothesis_ref`.

Legacy workspaces without `n000` or without `hypothesis_ref` are invalid under
the strict hypothesis contract.

Introduce a later mechanism hypothesis with `phase=hypothesis_generation`, an
`initial_mechanism_hypothesis`, and
`branch_context.relation=new_hypothesis_branch`. The initial object must carry
the new `hypothesis_id` and should identify the source hypothesis with
`parent_hypothesis_id`. Legacy `preflight` nodes are read-compatible aliases
for this function, but new decisions cannot create them.

R/P conformer generation is represented as `phase=candidate_generation` with a
conformer-specific `solution_ref.strategy`. Legacy
`phase=rp_conformer_generation` nodes remain readable, but new decisions cannot
create them.

Later nodes may include optional `solution_ref`:

```json
{
  "solution_id": "sol_scan_001",
  "strategy": "relaxed_scan_seed",
  "summary": "Generate a TS guess from a constrained bond-distance scan."
}
```

This groups computational search strategies within the same chemical
hypothesis. It does not create a second state machine: closure still uses only
`program_status` and `claim_verdict`, and failures remain diagnostics or
closure facts.

For same-hypothesis replacement of a failed search strategy, the agent records
an explicit branch-context decision:

```json
{
  "branch_context": {
    "relation": "new_solution_branch",
    "from_node": "n002",
    "anchor_node": "n000",
    "changed_variable": "solution_strategy",
    "reason_code": "route_failed"
  },
  "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_candidate_001"]},
  "solution_ref": {"solution_id": "sol_scan_002", "parent_solution_id": "sol_qst2_001"}
}
```

For `new_solution_branch`, `new_hypothesis_branch`, and `new_pathway_branch`,
the new node's `parent_node` must equal `branch_context.anchor_node`. The
`from_node` records the failed or triggering node; it is not the structural
parent unless it is also the anchor. For `new_solution_branch`, the anchor
must also equal the current hypothesis `source_node`, so same-hypothesis
replacement solutions remain mounted inside the hypothesis branch rather than
being lifted to a broader ancestor. The workspace validates this topology, but
it does not decide that a solution is exhausted, that a hypothesis is refuted,
or that the search should continue.

Legacy workspaces that predate this rule may be repaired through a validated
`update_workspace` decision with `payload.repair_branch_anchor`. The repair is
limited to non-running `new_solution_branch` nodes and requires
`new_anchor_node` to equal the node hypothesis `source_node`; it updates the
node, tree node, edge, and branch event lineage together and records a
`lineage_repairs` audit entry.

## Evidence Roles

Evidence `role` is a free-form string, not a fixed enum. The following roles
have specific consumers (validators, finalizers, report reader); use them
verbatim so downstream checks find them:

- `initial_mechanism_hypothesis` — required to close an `endpoint` or
  `hypothesis_generation` node that promotes a hypothesis.
- `endpoint_conformer_ensemble` — graph-preserving R/P conformers generated
  under a `candidate_generation` strategy.
- `selected_endpoint_conformer` — selected R/P representative with explicit
  ensemble provenance and selection rationale.
- `endpoint_minimum_gate` — endpoint stationary-minimum validation; it may be
  owned by `endpoint` for supplied structures or by the conformer
  `candidate_generation` node for generated representatives.
- `tsfreq_gate`, `mode_assignment` — TS/Freq validation gates.
- `connectivity_gate`, `irc_endpoint_assignment` — connectivity validation
  gates.
- `stereochemical_connectivity_gate` — required when the active hypothesis
  declares stereochemical requirements.
- `endpoint_identity_gate`, `intermediate_identity_gate`,
  `electronic_structure_gate`, `state_character_gate`,
  `shared_basin_consistency_gate` — mechanism-identity reflection gates.
- `pathway_audit_summary` — pathway audit conclusion. For `pathway_audit`,
  register this before `end_node` and include
  `quality.strict_pathway_decision` as `accepted` or `pathway_not_accepted`.
- `previous_attempt_summary` — used with `continue_parent` after a
  program-level failure on a prior attempt for the same scientific claim.
  Cite it from `branch_context.evidence_refs` so the failed attempt is
  machine-queryable without grepping `reason_code` text.

Other roles are permitted; they simply won't be consumed by the built-in
validators or finalizers.

## Workspace State Files

- `mechanism_model.hypotheses[]`: active, supported, refuted, or superseded
  working mechanism hypotheses.
- `mechanism_model.accepted_facts[]`: accepted TS facts written only by
  `accepted_audit` after TS/Freq and connectivity gates are both present.
- `pathway_model.json`: pathway and step topology. Hypotheses may reference a
  pathway step, but do not duplicate pathway structure.

The workspace validator checks required files, node JSON records, initial
`n000` structure, hypothesis references, optional solution lineage consistency,
explicit branch provenance after graph jumps, current focus, append-only
evidence identity, and forbidden public fields. A terminal unresolved node with
no running follow-up is reported as a warning/fact, not as an invalid workspace;
the agent decides whether to continue, stop, or ask the user.
