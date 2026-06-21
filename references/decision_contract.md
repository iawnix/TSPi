# Decision Contract

A decision JSON is the only mutation instruction channel.

Common shape:

```json
{
  "schema_version": "ts-decision",
  "action": "start_node",
  "rationale": "Open a TS/Freq validation node for the candidate from n003.",
  "evidence_refs": ["ev_candidate_001"],
  "report_ref": {
    "report_id": "rep_20260620T010000",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "phase": "tsfreq_validation",
    "hypothesis": "The candidate is a first-order saddle point for C-N formation.",
    "expected_evidence": ["gaussian_output", "imaginary_mode_summary"]
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
validates both the JSON contract and workspace-context requirements. For
example, starting a replacement branch after a terminal unresolved node must
include `payload.backtrack`; the same check is enforced again inside
`start_node` before any node files are written.

`update_workspace` may append evidence, knowledge, or provenance. It cannot
close a node, write a verdict, accept a TS, or rewrite a pathway.

Machine authority is `ts_workspace/contracts/decision.schema.json`, the pure
Python decision validator, and the workspace-aware decision preflight used by
the public CLI.
