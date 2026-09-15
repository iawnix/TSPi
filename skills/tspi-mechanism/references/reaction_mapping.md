# Reaction Mapping Capability

The first registered mechanism analysis is `reaction.mapping.validate@1`.
It validates a mapping supplied by Root; it is deliberately not an atom-mapping
generator.

## Discovery

```text
ts_state mode=capabilities capabilityKind=analysis
ts_state mode=capabilities capabilityKind=analysis query=reaction.mapping.validate@1
```

The compact index reports input/output roles. The exact query returns input and
parameter schemas, limits, parser version, and known limitations. Runtime readiness for external programs is separate from this
local analysis capability.

## Public analysis call

`ts_analyze` accepts an open `nodeId`, one or more registered XYZ artifacts on
each side, and explicit zero-based local references:

```json
{
  "operation": "run",
  "nodeId": "node_12",
  "capability": "reaction.mapping.validate",
  "capabilityVersion": "1",
  "inputArtifacts": {
    "reactants": ["art_0123456789abcdef01234567"],
    "products": ["art_89abcdef0123456701234567"]
  },
  "parameters": {
    "mapping": [
      {
        "reactant": {"species": 0, "atom": 0},
        "product": {"species": 0, "atom": 0}
      }
    ]
  }
}
```

The host resolves logical IDs and records a Node-owned deterministic activity.
Physical paths are never supplied by Root.
Species indices address list positions. Repeating an artifact ID represents
separate occurrences of the same species (for example, two water molecules);
the same ID can also appear on both sides for an unchanged catalyst. Each side
supports up to 64 species and 4096 total atoms, and the map supports up
to 4096 pairs. This call checks an existing map; it does not order the next task.

## Result

The result contains an analysis artifact and a summary of verdict, counts and
diagnostics. The full mapping and source bindings live in the artifact:

- `valid`, `complete`, and `verdict` (`valid`, `inconclusive`, or `invalid`);
- mapped pair count and reactant/product atom counts;
- whole-side and mapped element counts;
- unmapped references and element-mismatch diagnostics;
- source artifact IDs and digests in the artifact provenance.

`valid` requires every atom on both sides to be mapped exactly once, matching
elements, and equal whole-reaction element counts. An incomplete mapping is not
silently completed. A partial map with no contradictions is `inconclusive`;
duplicate references, wrong elements, unequal whole-side counts, or an empty
map are `invalid`, including when coverage is partial.

Record a semantic Observation with `ts_change` only when the result is used as
evidence. `candidate_refs` exposes three facts: element-preserving bijection,
coverage completeness, and pair count. Use the selected `artifactId` and
`candidateId` with the existing `record_observation` candidate variant; supply
the scientific concept, subject, and interpretation. For example, the operation
inside an ordinary `ts_change` request is:

```json
{
  "op": "record_observation",
  "local_ref": "mapping_check",
  "nodeRef": "node_12",
  "candidate": {"artifactId": "<returned artifactId>", "candidateId": "candidate_1"},
  "conceptId": "reaction.mapping.element_bijection",
  "subjectRef": "<the mapping being studied>",
  "summary": "<interpretation restricted to element correspondence>"
}
```

The kernel derives the value, datatype, unit, qualifiers and provenance and
rechecks the analysis against its source XYZ files. Candidate ownership stays
with the producing Node. The embedded `ts-analysis-observation-candidates/1`
record has an analysis producer and no calculation intent.

## Limits

The capability does not decide whether a bond change is chemically plausible,
whether a proton should be implicit, whether symmetry-equivalent maps are
scientifically equivalent, or whether a TS is connected to the endpoints.
Plain XYZ does not establish isotope, charge, spin or bond identity; a `valid`
map therefore establishes an element-preserving bijection only.
Use structural comparison, endpoint identity, TS validation, and the relevant
method evidence separately.
