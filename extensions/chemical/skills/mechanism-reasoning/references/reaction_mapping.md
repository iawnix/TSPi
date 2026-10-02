# Reaction Mapping Capability

The registered mechanism analysis `reaction.mapping.validate@1` validates a
mapping supplied by Root. It does not invent an atom map.

## Discovery And Call

```text
research_read mode=capabilities capabilityKind=analysis
research_read mode=capabilities capabilityKind=analysis query=reaction.mapping.validate@1
```

Call `analysis_run` with an open `nodeId`, registered XYZ Artifact IDs, and an
explicit zero-based mapping. Physical paths never belong in the request.
Species indices address list positions; repeating an Artifact ID represents
separate occurrences of the same species. Respect the capability's reported
limits.

## Result

The result contains an analysis Artifact and a summary of validity, coverage,
counts, diagnostics, source IDs, and digests. A valid map covers every atom on
both sides exactly once, matches elements, and preserves whole-reaction element
counts. A partial map without contradictions is inconclusive; duplicate
references, wrong elements, unequal counts, or an empty map are invalid.

When the result supports a scientific statement, create a `FactFinding` through
`research_change` with the producing `node_id`, a concise statement, `kind=fact`, the
relevant value and datatype, and the analysis Artifact in `source_refs`. Record
an incomplete or chemically ambiguous map as an `IssueFinding`. Do not copy
parser diagnostics into the map as if they were facts.

## Limits

This capability does not decide whether a bond change is chemically plausible,
whether a proton is implicit, whether symmetry-equivalent maps are equivalent,
or whether a transition state reaches endpoints. XYZ alone does not establish
isotope, charge, spin, or bond identity; use structural comparison and the
endpoint and transition-state Skills separately.
