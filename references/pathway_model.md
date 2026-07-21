# Pathway Model

`pathway_model.json` stores multiple pathway hypotheses at the same time. A
single-step branch and a multi-step branch may coexist until evidence supports,
refutes, or supersedes them.

Minimal shape:

```json
{
  "schema_version": "ts-pathway",
  "focus_pathway_id": "p_two_step_001",
  "pathways": [
    {
      "pathway_id": "p_two_step_001",
      "label": "two-step via Int1",
      "pattern": "R->TS1->Int1->TS2->P",
      "status": "active",
      "steps": [
        {
          "step_id": "s1",
          "from": "R",
          "to": "Int1",
          "status": "active"
        }
      ]
    }
  ]
}
```

Allowed pathway and step statuses:

- `proposed`
- `active`
- `supported`
- `refuted`
- `superseded`
- `accepted`

Branching appends events in `tree.json.branch_events[]`; it never deletes old
nodes or hides a rejected branch.

`pathway_audit` nodes may be recorded as `audit_nodes` on a pathway or step, but
their phase-level `claim_verdict` must not automatically mutate the audited step
to `supported` or `refuted`. Pathway or step status should change only from
elementary-step evidence or an explicit accepted-pathway contract. Whether to
continue with a new hypothesis branch after a negative audit is an agent
decision, not a validator-enforced branch rule.
Every `pathway_audit` start decision must include `payload.pathway_ref` with the
audited `pathway_id` and `step_id`; without that reference the audit cannot be
attached to `pathway_model.json`. Before closing the audit, register exactly
what the audit decided as a `pathway_audit_summary` evidence record with
`quality.strict_pathway_decision=accepted` or
`quality.strict_pathway_decision=pathway_not_accepted`.
`claim_verdict=supported` then means the audit decision is supported, not that
the pathway is necessarily accepted.
For strict user requests such as mandatory IRC and supplied R->P proof, a
negative audit means the audited branch is not accepted. The agent should open a
new scientifically justified branch unless the user stops the run or the audit
also documents that no meaningful branch remains.
