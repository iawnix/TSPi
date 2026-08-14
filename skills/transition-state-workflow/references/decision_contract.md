# Decision Contract

New mutations use `ts-decision/3`. A decision records the Root Agent's chosen
action; the Kernel adds no research strategy.

Every decision contains `decision_id`, `action`, `rationale`, unique
`basis_refs`, current `report_ref`, current `base_revision`, and an
action-specific `payload`.

## Start Node

```json
{
  "schema_version": "ts-decision/3",
  "decision_id": "dec_start_n003",
  "action": "start_node",
  "rationale": "Test whether the selected geometry is a first-order saddle point.",
  "basis_refs": ["claim_step_001", "nodes/n002/outputs/candidate.xyz"],
  "report_ref": {"report_id": "<current>", "workspace_root": "<root>"},
  "base_revision": "sha256:<current>",
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

Use the templates under `assets/templates/decision/`, bind the live report and
revision, validate, then apply the exact same JSON.
