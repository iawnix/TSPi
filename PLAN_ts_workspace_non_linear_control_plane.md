# PLAN: Non-Linear `ts_workspace` Control Plane

Created: 2026-07-01 03:56:48 CST

## Confirmed Contract Choices

- `branch_context` is mandatory for every `start_node` after the initial `n000`.
- `lineage_scope` is removed. Branch scope is derived only from `branch_context.relation`.
- Legacy compatibility is not preserved. Remove old `payload.backtrack`, `ledger_refs`, and implicit last-node behavior instead of keeping aliases.

## Goal

Make `ts_workspace` a typed mutation gate and consistency checker, not a research-path decision maker. The agent decides whether to continue, retry with a new computational route, switch chemical hypothesis, switch pathway topology, stop, or ask the user. `ts_workspace` only records that decision and validates that the declared references and evidence are structurally consistent.

## Design Rationale

Transition-state research is a hypothesis graph, not a linear pipeline. A failed calculation route may mean a bad TS guess, a bad conformer, a bad electronic-state assumption, a wrong elementary-step model, a scheduler/runtime failure, or an actually refuted chemical hypothesis. Those meanings are chemically different, and they cannot be inferred safely from node order or from a local `claim_verdict` alone.

The agent owns research judgment because it can compare chemical hypotheses, mechanism alternatives, artifact diagnostics, and user constraints such as mandatory IRC and strict R->P proof. `ts_workspace` owns structural discipline: it creates nodes from explicit decisions, verifies that required fields and references exist, records state changes, and prevents unsupported accepted-TS or pathway claims.

`branch_context` makes the agent's research intent explicit at the moment a node is created. This replaces hidden control flow based on the most recently written node. The workspace can then validate the declared graph relation without deciding why the branch should exist.

`lineage_scope` is removed because it creates a second vocabulary for the same branch meaning. The branch level should be derived from `branch_context.relation`; otherwise a decision could say `relation=new_solution_branch` while also saying `lineage_scope=hypothesis`, forcing validators to choose which field is authoritative.

Legacy aliases are intentionally not preserved. This is a contract correction, not a compatibility extension. Keeping `payload.backtrack`, `ledger_refs`, or implicit last-node behavior would preserve the ambiguity that caused the workspace to act too much like a linear workflow controller.

Evidence gates remain strict, but their role is limited. They prevent overclaiming an accepted TS or accepted pathway when TS/Freq, IRC/connectivity, endpoint assignment, stereochemical matching, or pathway audit evidence is missing. They do not decide whether the next branch should be another solution, a new hypothesis, a new pathway, or a stop.

## Non-Goals

- Do not let `ts_workspace` infer the next research action from node verdicts.
- Do not infer replacement branches from `ordered_node_ids[-1]`.
- Do not treat a failed solution route as a failed chemical hypothesis.
- Do not turn `report_workspace` into a recommender for next actions.

## New `start_node` Contract

`n000` remains the only start node that does not require `branch_context`.

Every later `start_node` must include:

```json
{
  "payload": {
    "parent_node": "n000",
    "phase": "candidate_generation",
    "hypothesis_ref": {"hypothesis_id": "hyp_0001"},
    "solution_ref": {"solution_id": "sol_scan_002"},
    "branch_context": {
      "relation": "new_solution_branch",
      "from_node": "n002",
      "anchor_node": "n000",
      "reason_code": "route_failed",
      "changed_variable": "solution_strategy"
    }
  }
}
```

`parent_node` remains the structural parent in the node graph. `branch_context` is the agent-declared research relation. These two fields may point to different nodes.

## `branch_context.relation` Values

### `continue_parent`

Use when the new node is the normal child of an existing node.

Validation:

- `parent_node` exists.
- `anchor_node`, if present, exists.
- `from_node`, if present, exists.
- mechanism phases still require valid `hypothesis_ref`.

No branch replacement or retry meaning is inferred.

### `new_solution_branch`

Use when the chemical hypothesis remains viable but the computational/search route changes.

Validation:

- `from_node` exists.
- `anchor_node` exists.
- new node has `solution_ref.solution_id`.
- if `from_node` has `hypothesis_ref`, the new node must keep the same `hypothesis_id`.
- new `solution_ref.solution_id` must differ from the `from_node` solution id when `from_node` has one.

No validator may decide that the old solution was exhausted. That judgment belongs only in the agent rationale and closure facts.

### `new_hypothesis_branch`

Use when the agent chooses a different chemical explanation.

Validation:

- `from_node` exists.
- `anchor_node` exists.
- new node has a valid `hypothesis_ref`.
- new hypothesis must differ from the old hypothesis when `from_node` has one.
- old hypothesis status is not changed unless a closure explicitly requests it with a permitted impact scope.

### `new_pathway_branch`

Use when the agent changes the pathway topology or pathway step being tested.

Validation:

- `from_node` exists.
- `anchor_node` exists.
- new node has valid `pathway_ref`.
- pathway and step records exist or are explicitly created by the mutation contract.
- a negative `pathway_audit` does not automatically create this relation.

### `administrative_followup`

Use for operational reruns or repairs: Gaussian crash, scheduler failure, parser failure, wrong input file, missing artifact, corrupted fetch, or similar non-chemical problems.

Validation:

- `from_node` exists.
- `reason_code` is required.
- no hypothesis, prediction, pathway, or solution is marked refuted because of this relation.

## Removed Concepts

Remove `payload.backtrack` from decision schema and templates.

Remove `lineage_scope` from:

- decision schema
- decision validator
- workspace validator
- tree event schema
- report output
- templates
- docs
- tests

Replace `tree.backtrack_events` with a neutral branch event name, for example:

```json
{
  "branch_events": [
    {
      "event_id": "br_0001",
      "relation": "new_solution_branch",
      "from_node": "n002",
      "anchor_node": "n000",
      "new_node": "n003",
      "reason_code": "route_failed",
      "changed_variable": "solution_strategy"
    }
  ]
}
```

## Validator Changes

### `decision_context.py`

Remove the current logic that uses the last written node as implicit context:

```python
previous_id = ordered_node_ids[-1]
```

Replace it with explicit validation of `payload.branch_context`.

The validator must not require a new node to reference the most recent node. It should only validate the nodes named by the agent in `parent_node` and `branch_context`.

### `workspace.py`

Remove adjacent-node replacement validation:

```python
for index, node_id in enumerate(ordered_node_ids[1:], start=1):
    previous_id = ordered_node_ids[index - 1]
```

Replace it with graph-level checks:

- every non-`n000` node has `branch_context`;
- all referenced nodes exist;
- branch events match node payloads;
- relation-specific invariants hold;
- no branch event implies a verdict or status change by itself.

Keep unresolved terminal nodes as warnings/facts only. They must not make the workspace invalid.

## Finalizer Changes

Add `closure.mechanism.impact_scope`:

```json
{
  "mechanism": {
    "impact_scope": "solution_only"
  }
}
```

Allowed values:

- `solution_only`
- `prediction`
- `pathway_step`
- `hypothesis`

Propagation rules:

- `solution_only`: record node closure and solution facts only; do not mutate pathway or hypothesis status.
- `prediction`: update only the named prediction status.
- `pathway_step`: allow pathway step status changes.
- `hypothesis`: allow hypothesis refute/supersede/revise actions.

Default for failed, refuted, or inconclusive mechanism closures should be `solution_only` unless the decision explicitly declares a broader impact scope.

## Evidence Gate Changes

Keep strict accepted-TS gates separate from branch decisions.

For roles such as `tsfreq_gate`, `connectivity_gate`, `stereochemical_connectivity_gate`, and `pathway_audit_summary`, require machine-generated validation artifact metadata:

```json
{
  "source_files": [],
  "source_sha256": "",
  "parser_name": "",
  "parser_version": "",
  "normal_termination": true,
  "diagnostics": []
}
```

`ts_workspace` validates artifact presence, hash consistency, parser metadata, normal termination facts, and role/phase ownership. It still does not decide whether to open a new branch.

## Terminology Changes

Replace `ledger` wording with state/model wording:

- `workspace ledgers` -> `workspace state files`
- `root ledger writes` -> `root state writes`
- `ledger_refs` -> `workspace_state_refs`

`decision_log.jsonl` may remain a decision log because it is append-only. Other files are state/model files, not ledgers.

## Report Changes

`report_workspace` should expose facts for the agent, not instructions.

Add:

```json
{
  "workspace_state_refs": {},
  "branch_frontiers": [
    {
      "node_id": "n002",
      "lifecycle": "closed",
      "claim_verdict": "refuted",
      "has_outgoing_branch": false
    }
  ],
  "readiness": {
    "structural_valid": true,
    "highest_validated_layer": "connectivity",
    "strict_r_to_p_ready": false,
    "blocking_evidence": ["pathway_audit_summary"]
  }
}
```

Do not include recommended next actions.

## Template Changes

Update all runtime templates under `templates/decision/`:

- include mandatory `branch_context` for every post-`n000` `start_node`;
- remove `payload.backtrack`;
- remove `lineage_scope`;
- replace `ledger_refs` references in report examples with `workspace_state_refs`.

Test fixtures must be updated after templates. Tests remain regression coverage, not operating examples.

## Testing Plan

Add tests for:

- post-`n000` `start_node` without `branch_context` is rejected;
- `new_solution_branch` with changed hypothesis is rejected;
- `new_solution_branch` with missing/new duplicate `solution_ref` is rejected;
- `new_hypothesis_branch` does not mutate old hypothesis status by itself;
- `administrative_followup` cannot refute hypothesis/pathway;
- non-linear branch from an older node is accepted even when the most recent node is terminal unresolved;
- workspace validation no longer uses adjacent-node order as branch provenance;
- reports expose `workspace_state_refs`, `branch_frontiers`, and `readiness`;
- no output contains `ledger_refs`, `payload.backtrack`, or `lineage_scope`.

## Implementation Order

1. Update docs and terminology.
2. Update schemas for `branch_context`, `branch_events`, `impact_scope`, and `workspace_state_refs`.
3. Update decision validator.
4. Update workspace validator.
5. Update engine writes from backtrack events to branch events.
6. Update finalizer propagation with `impact_scope`.
7. Update report builder.
8. Update templates.
9. Update tests.
10. Run source tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

11. Commit and push the maintenance repo.
12. Sync to installed skill under `/home/iaw/TS/.agents/skills/transition-state-workflow`.
13. Run installed runtime validation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_in_runtime.py -m pytest -q -p no:cacheprovider
python3 scripts/ts_render.py diagnostic --json
```

## Acceptance Criteria

- `ts_workspace` accepts explicitly declared non-linear branches.
- `ts_workspace` rejects structurally incomplete or inconsistent decisions.
- No validator infers branch provenance from the most recent node.
- No failure propagates beyond its declared `impact_scope`.
- Strict accepted TS still requires TS/Freq, IRC/connectivity, endpoint proof, and declared stereochemical gate when applicable.
- User-facing wording no longer uses `ledger` except for historical migration notes if needed.
