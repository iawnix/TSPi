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

## v3 Hypothesis Model

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
`start_node` after `init_workspace`. Use `phase=endpoint` or `phase=preflight`.
The `n000` decision must include `payload.initial_mechanism_hypothesis`.

Close `n000` after endpoint provenance, charge/multiplicity, atom-order
mapping, source hashes, reaction-center delta, and initial mechanism evidence
are recorded. Candidate generation starts at `n001` with `parent_node=n000` and
`payload.hypothesis_ref`.

Legacy workspaces without `n000` or without `hypothesis_ref` are invalid under
the v3 contract.

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
an explicit backtrack decision:

```json
{
  "backtrack": {
    "from_node": "n002",
    "to_node": "n000",
    "changed_variable": "solution_strategy",
    "reason_code": "route_failed",
    "lineage_scope": "solution"
  },
  "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_candidate_001"]},
  "solution_ref": {"solution_id": "sol_scan_002", "parent_solution_id": "sol_qst2_001"}
}
```

The workspace validates this as provenance only. It does not decide that a
solution is exhausted, that a hypothesis is refuted, or that the search should
continue.

## Ledgers

- `mechanism_model.hypotheses[]`: active, supported, refuted, or superseded
  working mechanism hypotheses.
- `mechanism_model.accepted_facts[]`: accepted TS facts written only by
  `accepted_audit` after TS/Freq and connectivity gates are both present.
- `pathway_model.json`: pathway and step topology. Hypotheses may reference a
  pathway step, but do not duplicate pathway structure.

The workspace validator checks required files, node JSON records, initial
`n000` structure, hypothesis references, optional solution lineage consistency,
explicit backtrack provenance after branch jumps, current focus, append-only
evidence identity, and forbidden public fields. A terminal unresolved node with
no running follow-up is reported as a warning/fact, not as an invalid workspace;
the agent decides whether to continue, stop, or ask the user.
