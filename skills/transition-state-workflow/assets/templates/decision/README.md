# Decision Operation Templates

Each JSON file is one operation snippet for the `operations` array accepted by
`ts_workspace_decision_draft`. The files document the v5 vocabulary; they are
not a prescribed research sequence.

Replace `${PLACEHOLDER}` values, combine only the operations needed for one
atomic research decision, and provide a separate `rationale` and `basisRefs`.
Records created in the same draft use `$local_ref` references. Do not invent
Claim, ResearchNode, Observation, Finding, GateSpec, ValidationResult, Decision,
or acceptance IDs. The Kernel allocates those identifiers, binds the current
Context projection and workspace revision, and returns a frozen
`ts-research-decision/2`.

Pass that exact Decision to `ts_workspace_decision_validate`, then to
`ts_workspace_decision_apply`. Any change requires a new draft.

One Decision may create at most one Phase, start at most one ResearchNode, and
complete at most one ResearchNode. It may start and complete that same Node, or
combine an existing Node completion with one successor start when the successor
explicitly depends on the completed Node. Use separate Decisions for unrelated
or parallel transitions.
