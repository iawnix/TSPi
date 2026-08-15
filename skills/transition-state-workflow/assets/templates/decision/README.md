# Decision Templates

These examples are argument objects for `ts_workspace_decision_draft`. They
cover the generic mutation surface but are not a prescribed research sequence.
The Root Agent chooses objectives, parents, Claims, facts, calculations, and
when to evaluate or close work.

Render `${PLACEHOLDER}` values and call the draft tool. Do not add
`decision_id`, `report_ref`, `base_revision`, Evidence `evidence_id`, or Gate
`gate_result_id`: the deterministic workspace Kernel adds those fields and
returns a canonical `ts-decision/3`. Pass that returned Decision unchanged to
validate and apply.
