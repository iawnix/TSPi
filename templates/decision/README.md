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

Typical endpoint-first sequence:

1. `start_endpoint_n000.json`
2. `update_endpoint_evidence.json`
3. `end_endpoint_n000_supported.json`
4. `start_candidate_generation.json`
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

For a negative pathway audit, use `update_pathway_audit_not_accepted.json` and
`end_pathway_audit_not_accepted.json`. That closes the current mechanism
branch only. If a new hypothesis branch is scientifically justified, start it
with `start_replacement_branch.json` and explicit `payload.backtrack`
provenance.
