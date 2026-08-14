# Decision Templates

These examples cover the generic `ts-decision/3` mutation surface. They are
not a prescribed research sequence. The Root Agent chooses objectives,
parents, claims, calculations, and when to evaluate or close work. The
deterministic workspace kernel only checks references, immutable history,
evidence state, Gate policies, and transaction consistency.

Render `${PLACEHOLDER}` values, bind the current `report_ref` and
`base_revision`, then run decision preflight before applying a mutation.
