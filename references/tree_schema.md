# Tree Schema

Load this whenever creating, updating, or auditing a TS-search workspace.

## Directory Layout

```text
tssearch_<system>/
├── manifest.json
├── tree.json
├── nodes/
│   └── nNNN_short_label/
│       ├── node.json
│       ├── reflection.md
│       ├── inputs/
│       ├── outputs/
│       ├── scratch/
│       └── parsed/
└── reports/
```

Use stable node IDs such as `n010_endpoint_opt_reactant`, `n120_neb_xtb_candidate`, `n230_gaussian_tsfreq`, or `n490_qbics_dmecp_preflight`.

## Required `manifest.json`

```json
{
  "system": "group5",
  "created_at": "2026-06-05T00:00:00+08:00",
  "charge": -1,
  "multiplicity": 2,
  "root": "/abs/path/tssearch_group5",
  "node_schema": "ts-node-v2",
  "current_accepted_ts": null
}
```

## Required `tree.json`

```json
{
  "schema": "tssearch-branching-tree-v2",
  "nodes": {},
  "active_frontier": [],
  "closed_nodes": [],
  "accepted_nodes": [],
  "events": [],
  "backtrack_events": []
}
```

## Required `node.json` Fields

Every node must record:

```json
{
  "schema": "ts-node-v2",
  "node_id": "n230_gaussian_tsfreq",
  "parent_id": "n220_candidate",
  "input_refs": [],
  "stage": "gaussian_tsfreq_validation",
  "operation": "gaussian-tsfreq",
  "lifecycle_state": "closed",
  "run_state": "completed",
  "claim_status": "tsfreq_validated",
  "outcome": "tsfreq_validated",
  "outcome_code": null,
  "claim_level": "tsfreq_validated_only",
  "hypothesis": "This candidate is the O7-H to O8-H rearrangement saddle.",
  "changed_variables": {
    "method": "UM062X/def2SVP",
    "route": "Opt(TS,CalcFC) Freq"
  },
  "artifact_policy": {
    "input_dir": "nodes/n230_gaussian_tsfreq/inputs",
    "output_dir": "nodes/n230_gaussian_tsfreq/outputs",
    "run_cwd": "nodes/n230_gaussian_tsfreq/outputs",
    "scratch_dir": "nodes/n230_gaussian_tsfreq/scratch",
    "engine_outputs": "write engine logs, checkpoints, restart files, trajectories, and candidates under output_dir or scratch_dir, never workspace root"
  },
  "evidence": {
    "input": "/abs/path/job.gjf",
    "output": "/abs/path/job.out",
    "parsed_summary": "/abs/path/parsed/summary.json"
  },
  "display": {
    "title": "n230 Gaussian TS/Freq",
    "summary": "Gaussian TS/Freq validated exactly one intended imaginary mode; connectivity is not yet proven.",
    "metrics": {}
  },
  "decision": "prepare_irc"
}
```

The canonical state fields are `lifecycle_state`, `run_state`, `claim_status`,
`outcome`, `outcome_code`, and `claim_level`. Author only
`lifecycle_state`/`run_state`, `claim_status`, and (for failures) `outcome` and
`outcome_code`; successful outcomes and `claim_level` are derived by
`finalize-node` from `claim_status` and the validator rejects hand-written
values that disagree with the derivation. Do not write a second canonical
state into `tree.json`. New workspaces must not write obsolete or duplicated
state fields such as `status`, `failure_type`, `children`, `backtrack_target`,
`current_best`, `accepted_ts`, `backtrack_edges`, or `branch_decisions`.
Workspaces containing those fields are invalid for the normal workflow,
validator, and explorer.

Program-specific or chemistry-specific failure labels do not belong in
`outcome`. Store them in `outcome_code` on `node.json` or `reason_code` on
`backtrack_events[]`. Examples include `scf_nonconvergence`,
`qst2_internal_coordinate_failure`, `wrong_reaction_coordinate`, and
`irc_not_connected`.

Do not store a global best candidate in `tree.json`. Candidate ranking and
selection are node-local evidence: record the candidate id, quality gates, and
promotion decision in the candidate node's summary/metadata, then create the
Gaussian validation child from that node. This keeps failed and superseded
candidates available for backtracking without letting one root-level cache hide
the branch history.

All engine execution must be node-scoped. For Gaussian, xTB, QBICS, ASE/NEB,
scan, dimer, and related tools, use `nodes/<node_id>/outputs` as the process
working directory and read prepared inputs from `../inputs` or
`nodes/<node_id>/inputs`. Engine-created logs, checkpoints, restart files,
trajectories, candidate structures, and parsed summaries must stay under
`nodes/<node_id>/outputs`, `nodes/<node_id>/parsed`, or node-local scratch. The
workspace root is reserved for root metadata files and top-level reports only.
For local or already-staged remote xTB/QBICS/ASE commands, prefer
`scripts/ts_node_exec.py --workspace <root> --node-id <node_id> -- <command> ...`
so fixed-name files such as `xtbopt.xyz`, `.mwfn`, trajectories, and runner logs
cannot land in the workspace root. For Gaussian inputs under
`nodes/<node_id>/inputs`, `scripts/run_remote_gaussian.py` uses
`nodes/<node_id>/outputs` as the remote run directory automatically.
`ts_node_exec.py` controls the process cwd and metadata only; it does not close
or promote scientific state. Use `start-node` before launch and `finalize-node`
after parsing evidence.

Use `claim_status=accepted_ts` only after both Gaussian TS/Freq validation and
connectivity validation pass for the intended reaction. A stopped job is
`run_state=stopped`, `claim_status=not_evaluated`, and
`outcome=administrative_stop`, not a chemical failure.

Use `input_refs` for multi-input dependencies that are not the single primary
tree parent. The tree remains a lineage tree with one `parent_id`, while
`input_refs` records computational dependencies such as QST2 endpoints,
endpoint-pair validation inputs, IRC reference endpoints, or multi-structure
comparison inputs. Create these nodes with repeated
`scripts/ts_hypothesis_workspace.py decision-card --input-ref <node_id>` rather
than hand-editing JSON. The normalizer renders `input_refs` as separate
dependency edges and the validator rejects missing referenced nodes.

Use `claim_status=endpoint_minima_ready` with
`outcome=endpoint_minima_validated` for endpoint Opt/Freq/minima identity checks
that passed before any TS candidate or TS connectivity claim exists. This is a
prerequisite endpoint-readiness claim, not evidence that a transition state
connects the endpoints.

Use `claim_status=candidate_found` only when an upstream parent or dependency
node has `claim_status=endpoint_minima_ready`. A scan, NEB, QST, dimer, dMECP,
or guessed geometry from unvalidated endpoint hypotheses must stay
`not_evaluated`, `ambiguous`, or `rejected` until endpoint readiness is recorded.

Use `scripts/ts_hypothesis_workspace.py start-node` when a prepared branch is
launched remotely or locally. It updates `node.json` to
`lifecycle_state=active`, sets `run_state=pending|running|parsing`, appends the
node to `tree.json.active_frontier`, and records a `start_node` event.

Completed nodes should be closed with
`scripts/ts_hypothesis_workspace.py finalize-node`. This command updates
`node.json`, `tree.json`, `evidence_registry.json`, `reflection.md`, optional
knowledge/model files, and accepted-TS manifest state together. Do not update
those files as independent manual edits unless repairing historical data, and
always validate after such a repair.

Use `scripts/ts_hypothesis_workspace.py record-backtrack` to write
`tree.json.backtrack_events[]`. The failed or backtracked `--from-node` is the
only node that receives the visible backtrack badge. If `--new-branch-node` is
provided, that node records `generated_from_backtrack_event_ids` as lineage
metadata but does not receive the failure/backtrack badge.

Backtracking never rewrites existing parent links. It records a cross-edge from
`from_node` to `to_node` so the failed branch remains auditable. The next
chemically distinct branch after an active backtrack should be an ordinary
child of `to_node`, or of `planning_focus.parent_for_new_branch` from the latest
`plan-next` packet. Use `input_refs` if the new branch depends on files or
observations from the failed node.

If that ordinary child branch already exists as the replacement attempt, the
backtrack event must name it with `new_branch_node`. The validator warns when a
failed or ambiguous branch has a later sibling under the same parent but no
matching `from_node -> to_node -> new_branch_node` backtrack event.

`planning_focus`, `context_policy`, `context_items`,
`suggested_backtrack_actions`, and `suggested_decision_cards` are generated
planning-packet fields. They are not valid `tree.json` fields and should not be
persisted in the workspace tree.

## Event Entry

Use normalized `events[]` entries whenever choosing, closing, or backtracking:

```json
{
  "event_id": "evt_n230_parse",
  "time": "2026-06-05T00:00:00+08:00",
  "node_id": "n230_gaussian_tsfreq",
  "event_type": "parse_result",
  "decision": "prepare_irc",
  "reason": "Exactly one imaginary frequency matches the intended reaction-center mode.",
  "evidence_refs": ["ev_n230_tsfreq_0001"]
}
```

`events[]` is the only runtime timeline input for the explorer. Append new
events in time order; the normalizer sorts by the ISO-8601 `time` field, so
array position is never authoritative.

## Backtrack Event Entry

Use `backtrack_events[]` for graph backtracking edges:

```json
{
  "id": "bt_n240_to_n180",
  "from_node": "n240_failed_tsfreq",
  "to_node": "n180_bridge_scan",
  "new_branch_node": "n250_restart_from_n240_final",
  "reason_code": "wrong_mode",
  "reason": "The imaginary mode was not the intended reaction-center motion.",
  "evidence_refs": ["ev_n240_wrong_mode_0001"],
  "event_state": "active",
  "created_at": "2026-06-05T00:00:00+08:00"
}
```

`event_state=active` means `plan-next` may use this event to route the next
branch to `to_node`. `resolved` and `superseded` events stay in the graph as
history but should not control the next branch parent.

A workspace may contain at most one `event_state=active` backtrack event.
`record-backtrack` enforces this by default, and the validator reports
`multiple_active_backtracks` if hand-edited data violates it. Use
`update-backtrack --event-state resolved` when the current active event is
finished, or `--supersede-active` when a new active event should replace the
current one.

Use `scripts/ts_hypothesis_workspace.py update-backtrack` for state changes on
existing backtrack events. Do not hand-edit `event_state`; the command appends a
timeline event and keeps the single-active invariant enforceable.

## Reflection File

Every failed or ambiguous node needs `reflection.md`:

```markdown
## Computational Outcome
What happened numerically, with exact error text or validation result.

## Mechanistic Implication
What the evidence implies about the proposed mechanism, electronic state, or endpoint references.

## Next Branch
What should be tried next and why this is chemically different from the failed branch.
```

## Tree Discipline

- Update the tree before running a new branch and again after parsing results.
- Use `finalize-node` for post-execution node closure so runtime state,
  evidence records, reflections, and tree indexes stay synchronized.
- Preserve failed logs and wrong-host runs as evidence; do not overwrite them.
- Do not remove closed branches. Mark them closed with a reason.
- Put a node in `active_frontier` only while it is actively pending, running, or
  parsing.
- Derive children from parent links; do not hand-maintain conflicting children
  arrays in multiple files.
- Use `input_refs` for non-tree dependencies; do not force QST2 or endpoint
  pair inputs into fake parent-child chains.
- Run engines from `nodes/<node_id>/outputs`; do not allow Gaussian `.chk`, xTB
  `xtbopt.xyz`/`xtbrestart`, QBICS `.mwfn`/trajectory files, or runner logs to
  appear at workspace root.
- User-visible evidence belongs in `evidence_registry.json`; node-local
  `evidence` pointers are convenience links only.
- If a branch used the wrong host, method, charge, multiplicity, or endpoint reference, make a new corrected branch instead of silently replacing files.
- Run `scripts/ts_validate_workspace.py --source <tssearch_root> --pretty`
  before using the explorer state as evidence.
