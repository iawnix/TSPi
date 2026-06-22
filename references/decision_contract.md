# Decision Contract

A decision JSON is the only mutation instruction channel.

The public schema version remains `ts-decision`, but v3 decisions are strict:
the first node must submit a structured initial hypothesis, and all later
mechanism phases must reference an existing hypothesis.

## Start `n000`

```json
{
  "schema_version": "ts-decision",
  "action": "start_node",
  "rationale": "Start endpoint-derived mechanism preflight.",
  "evidence_refs": [],
  "report_ref": {
    "report_id": "rep_20260622T010000",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "node_id": "n000",
    "phase": "endpoint",
    "hypothesis": "Initial endpoint-derived mechanism hypothesis.",
    "initial_mechanism_hypothesis": {
      "summary": "Concerted C-N formation on the singlet surface.",
      "derived_from": {},
      "structured_claim": {
        "reaction_center": {
          "forming_bonds": [{"atoms": [1, 2], "label": "C1-N2"}],
          "breaking_bonds": []
        },
        "reaction_class": ["bond_formation"],
        "elementary_step_model": "concerted",
        "electronic_model": {"surface": "ground_state"}
      },
      "testable_predictions": [],
      "required_evidence": ["initial_mechanism_hypothesis"],
      "uncertainties": [],
      "alternative_hypotheses": [],
      "evidence_refs": ["ev_hyp_0001"]
    },
    "expected_evidence": ["initial_mechanism_hypothesis"]
  }
}
```

`end_node n000` must close with endpoint/preflight facts. If supported, the
finalizer promotes `initial_mechanism_hypothesis` into
`mechanism_model.hypotheses[]`.

## Later Mechanism Nodes

```json
{
  "schema_version": "ts-decision",
  "action": "start_node",
  "rationale": "Open TS/Freq validation for the active hypothesis.",
  "evidence_refs": ["ev_candidate_001"],
  "report_ref": {
    "report_id": "rep_20260622T010500",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "parent_node": "n000",
    "phase": "tsfreq_validation",
    "hypothesis": "The candidate is a first-order saddle for hyp_0001.",
    "hypothesis_ref": {
      "hypothesis_id": "hyp_0001",
      "prediction_ids": ["pred_mode_001"]
    },
    "expected_evidence": ["gaussian_output", "imaginary_mode_summary"]
  }
}
```

`closure.mechanism.hypothesis_ref` must match the node's
`payload.hypothesis_ref`.

## Closure Revision

```json
{
  "mechanism": {
    "summary": "The imaginary mode does not follow the reaction center.",
    "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_mode_001"]},
    "revision": {
      "action": "refute_prediction",
      "prediction_ids": ["pred_mode_001"],
      "changed_variable": "reaction_center"
    },
    "evidence_refs": ["ev_mode_002"]
  }
}
```

Allowed actions:

- `init_workspace`
- `start_node`
- `end_node`
- `update_workspace`
- `ask_user`
- `stop`

`start_node`, `end_node`, and `update_workspace` require a `report_ref`.
`report_workspace` should be run before the decision is written.

The public `validate_decision --root <root> --decision-file <file>` preflight
validates both JSON shape and workspace-context requirements. Mutation commands
run the same validation internally before writing files.

`update_workspace` may append evidence, knowledge, or provenance. It cannot
close a node, write a verdict, accept a TS, rewrite a pathway, or mutate
`mechanism_model.hypotheses[]`.

Machine authority is `ts_workspace/contracts/decision.schema.json`, the pure
Python decision validator, and the workspace-aware decision preflight used by
the public CLI.
