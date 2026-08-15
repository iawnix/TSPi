# Decision Contract

New mutations use `ts-decision/3`. A Decision records the Root Agent's chosen
action; the Kernel adds no research strategy.

The Root Agent supplies `action`, `rationale`, `basisRefs`, and an
action-specific `payload` to `ts_workspace_decision_draft`. The Kernel binds
the current report and revision, allocates the Decision ID, and allocates IDs
for appended Evidence and Gate results. The returned canonical Decision
contains `decision_id`, `basis_refs`, `report_ref`, and `base_revision`.

## Start Node

```json
{
  "action": "start_node",
  "rationale": "Test whether the selected geometry is a first-order saddle point.",
  "basisRefs": ["claim_step_001", "nodes/n002/outputs/candidate.xyz"],
  "payload": {
    "node_id": "n003",
    "parent_node": "n002",
    "objective": "Optimize and characterize the selected saddle candidate.",
    "tags": ["gaussian", "tsfreq"],
    "claim_refs": ["claim_step_001"]
  }
}
```

The parent and tags record Root intent and history. They do not constrain later
methods or actions.

## Update Workspace

One update may contain one or more of:

- `append_claim`;
- `append_evidence`;
- `append_evidence_event`;
- `evaluate_gate`;
- `link_operation`;
- `set_focus_claim_refs`;
- `append_provenance`.

Claim and Evidence `kind` values are free versioned identifiers. Gates are
closed named policies because they execute deterministic scientific checks.
Draft Evidence omits `evidence_id`, and draft Gate evaluation omits
`gate_result_id`. Use `allocated_refs` from the draft/apply result when a later
Decision cites the newly created object.

## End Node

`end_node` binds one Node and a `result` containing:

- `outcome=completed|inconclusive|blocked|stopped`;
- a summary;
- zero or more explicit Claim updates;
- an optional named audit;
- open questions.

A Claim update must cite the Evidence and Gate results that justify it. The
Kernel never derives the update from the Node tag or program result.

An accepted audit is valid only when all Gate results required by its named
policy pass for the same target. `study_complete` is an explicit Root decision,
not a consequence of closing a Node.

Use the draft argument templates under `assets/templates/decision/`. Pass the
canonical Decision returned by the draft tool unchanged to validate and apply.
