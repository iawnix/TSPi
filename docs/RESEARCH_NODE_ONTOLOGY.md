# Research Node Ontology

This contract treats the workspace as a non-linear research tree. A node is a
bounded research act, not a mandatory chronological stage and not one remote
job.

## Node Types

| `node_type` | Responsibility | Primary authority |
|---|---|---|
| `intake` | Normalize user inputs, research scope, structures, constraints, and completion criteria. Reserved for `n000`. | Root agent |
| `mechanism` | Propose, compare, revise, or evaluate structured mechanism hypotheses from registered evidence. | Root agent |
| `candidate_search` | Generate TS, endpoint-conformer, intermediate, or crossing-point candidates. | Backend operator; Root selects candidates |
| `validation` | Generate evidence for a declared prediction or mechanism claim. | Backend operator; Root interprets evidence |
| `audit` | Audit a TS, elementary step, pathway, or complete study against registered evidence. | Root agent with optional independent review |

`phase` is a legacy field. New decisions use `node_type`.

## Validation Scopes

`validation_scope` is one of `tsfreq`, `connectivity`,
`electronic_structure`, `state_character`, `thermochemistry`,
`method_robustness`, or `geometry_identity`.

Frequency and IRC work share the `validation` node type but remain separate
scientific gates. The default representation is one `tsfreq` node followed by
one `connectivity` node. A combined execution may emit both only when it writes
independent evidence records and preserves their separate verdict boundaries.

## Recalculation

Recalculation is not a node type. A technical retry uses
`ts-calculation-intent/2 attempt_kind=retry` under the same node. A method
change that can alter the scientific conclusion opens a new node of the same
scientific type with `attempt_kind=recalculation`, cites the source node or
intent, and records `branch_context.relation=recalculation_of`.

## Outcomes

The following axes are independent:

- `node.lifecycle`: `running`, `closed`, or `stopped`;
- `program.outcome`: `success`, `failure`, or `not_run`;
- `hypothesis.status`: `supported`, `unsupported`, or `ambiguous`;
- `audit.status`: `accepted`, `not_accepted`, or `ambiguous`;
- remote job state remains an operational lifecycle and is never a scientific
  verdict.

`unsupported` means contradicted by a declared decision boundary. Missing or
conflicting evidence is `ambiguous`.

A pathway audit is stricter than the generic audit status axis: before closure,
it must cite `pathway_audit_summary` evidence with
`quality.strict_pathway_decision=accepted|pathway_not_accepted`, and the audit
status must match that decision.

## Authority Boundary

Backend, render, report, email, and review subagents return bounded JSON
results. They do not update hypothesis status, choose branches, or apply
workspace decisions. The Root Agent owns hypothesis falsification and the next
decision.
