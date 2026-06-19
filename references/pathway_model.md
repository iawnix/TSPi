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

Backtracking appends events in `tree.json.backtrack_events[]`; it never deletes
old nodes or hides a rejected branch.
