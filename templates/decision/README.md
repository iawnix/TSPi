# Runtime Decision Templates

These templates are the runtime starting point for `ts_workspace` mutations.
Use them when preparing a real decision JSON, then run:

```bash
python scripts/ts_workspace.py validate_decision --root <workspace> --decision-file decision.json
```

The placeholders use the literal form `${NAME}`. Replace every placeholder
with workspace-specific values before mutation. The templates define decision
shape, provenance, evidence roles, and closure semantics only. They do not
encode a fixed retry policy; branch choice remains a chemistry judgment.

Do not use files under `tests/` as runtime decision examples. Tests are allowed
to contain narrow fixtures and edge cases that are not complete operating
guidance.

Evidence paths are node-owned. A `tsfreq_validation` evidence record for
`n002` should cite an artifact under `nodes/n002/outputs/...`, not the
candidate node that originally generated the Gaussian log. When a node consumes
an upstream file, create `nodes/<node>/outputs/artifact_manifest.json` using
`templates/artifact_manifest.json` and put the upstream file under
`consumed_artifacts`.

Typical endpoint-first sequence:

1. `start_endpoint_n000.json`
2. `update_endpoint_evidence.json`
3. `end_endpoint_n000_supported.json`
4. `start_candidate_generation.json` for the first `solution_ref`
5. `update_candidate_evidence.json`
6. `end_candidate_generation_supported.json`
7. `start_tsfreq_validation.json`
8. `update_tsfreq_evidence.json`
9. `end_tsfreq_validation_supported.json`
10. `start_connectivity_validation.json`
11. `update_connectivity_evidence.json`
12. `end_connectivity_validation_supported.json`
13. `start_accepted_audit.json`
14. `end_accepted_audit_supported.json`
15. `start_pathway_audit.json`
16. `update_pathway_audit_accepted.json`
17. `end_pathway_audit_accepted.json`

If the active hypothesis declares `structured_claim.stereochemical_policy`,
`structured_claim.stereochemical_requirements`, or includes
`stereochemical_connectivity_gate` in `required_evidence`, register
`update_stereochemical_connectivity_evidence.json` during the
`connectivity_validation` node and include that evidence ref in the accepted
audit. Non-stereo hypotheses do not need this optional template.

For a failed computational path that the agent judges to be a solution failure
rather than a chemical-hypothesis failure, use `start_solution_branch.json`.
It keeps the same `hypothesis_ref`, assigns a new `solution_ref`, and records
`payload.branch_context.relation=new_solution_branch`. The template mounts the
new node under `payload.branch_context.anchor_node`; the failed or triggering
node is recorded separately as `payload.branch_context.from_node`.

For a negative pathway audit, use `update_pathway_audit_not_accepted.json` and
`end_pathway_audit_not_accepted.json`. That closes the current mechanism
branch only. If the agent decides a same-hypothesis solution branch remains
scientifically meaningful, start it with `start_solution_branch.json` and
explicit `payload.branch_context` provenance. If the chemistry itself is being
changed, create or revise the chemical hypothesis explicitly; do not encode
that as an automatic retry policy.
