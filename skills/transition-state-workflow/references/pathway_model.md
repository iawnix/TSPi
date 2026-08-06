# Pathway Model

`hypotheses.json.pathways[]` may hold competing single- and multi-step pathway
hypotheses. Branching appends nodes and events; it never deletes rejected
history.

```json
{
  "pathway_id": "p_two_step_001",
  "label": "two-step via Int1",
  "pattern": "R->TS1->Int1->TS2->P",
  "status": "active",
  "steps": [
    {"step_id": "s1", "from": "R", "to": "Int1", "status": "active"},
    {"step_id": "s2", "from": "Int1", "to": "P", "status": "proposed"}
  ]
}
```

Pathway and step status values remain explicit model state. A backend, parser,
candidate node, or validation node cannot change them.

## Pathway Audit

Use `node_type=audit, audit_scope=pathway`. Every pathway audit start decision
must include `payload.pathway_ref` with `pathway_id` and, when auditing one
step, `step_id`.

Before closing, register a `pathway_audit_summary` evidence record with:

```text
quality.strict_pathway_decision=accepted
```

or:

```text
quality.strict_pathway_decision=pathway_not_accepted
```

Then set `closure.audit.status=accepted|not_accepted` to match that strict
decision and cite the evidence. If the evidence is still ambiguous, do not
close the pathway audit; obtain the missing discriminator or stop the node
without a scientific audit verdict. `study_complete` is separate. A
not-accepted pathway branch does not complete a strict search while a
meaningful alternative branch remains.

## Multi-Step Requirements

For `R->TS1->Int1->TS2->P`:

- each TS has separate TS/Freq and connectivity evidence;
- the shared intermediate has identity and minimum evidence;
- step endpoint assignments refer to the same local intermediate basin;
- each accepted elementary step has an audit record;
- the pathway audit checks the complete ordered chain.

Geometry-only connectivity does not prove electronic timing, spin/state
character, or intermediate identity. Add the corresponding validation scopes
when those claims are part of the hypothesis.

## Audit Interpretation

Pathway audit nodes use `node_type=audit`, `audit_scope=pathway`, and an
explicit `closure.audit.status`. Their
verdict applies to the audit analysis, not automatically to pathway success.
