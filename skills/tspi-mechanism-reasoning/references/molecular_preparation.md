# Molecular reaction and structure capabilities

All capabilities use version `1`. Query their detail schemas before first use;
the examples below illustrate scientific choices, not a required sequence.

`reaction.parse` accepts either reaction SMILES plus one declared multiplicity
per component, or explicit `species`, `reactants` and `products`. Example:

```json
{
  "operation": "run", "nodeId": "node_1",
  "capability": "reaction.parse", "capabilityVersion": "1",
  "inputArtifacts": {},
  "parameters": {
    "reaction_smiles": "CCl.[OH-]>>CO.[Cl-]",
    "multiplicities": {"reactants": [1, 1], "products": [1, 1]}
  }
}
```

The resulting `ts-reaction-spec/1` includes explicit hydrogens, isotopes, formal
charge, declared spin, graphs, identity and stoichiometric occurrences. Separate
`ts-species-record/1` files are generated. Include participating catalysts and
spectators on the appropriate sides. `reaction.validate` checks a closed boundary;
electron/proton reservoirs need a separate model and return unsupported.

`reaction.mapping.generate` proposes graph-edit minima, bounded by `max_states`
and `max_candidates`. Its objective is not mechanistic likelihood. Symmetric
hydrogens may produce multiple equivalent mappings; truncated search cannot
establish uniqueness or global optimality. Explicit SMILES map labels remain
recorded but do not constrain the graph-edit search in version 1.

`reaction.bond_changes` accepts a complete explicit `mapping`, or a mapping
artifact plus explicit zero-based `candidate_index`. It returns formed, broken
and order-changed bonds plus reaction-center atoms. A selection remains the
Agent's declared correspondence, not proof of a mechanism.

`structure.reindex` applies that selected correspondence to ordered XYZ species
lists and writes two aligned endpoint files. The XYZ atom order must agree with
the graph used to define the mapping; element agreement alone cannot prove that
two same-element atoms have been identified correctly.

`structure.assemble_fragments` uses explicit rotation matrices and translations
in angstroms. It can evaluate several `placement_candidates` and flags close
interfragment contacts. It performs no optimization or automatic complex search.
Follow-up optimization/CREST/NEB is a separate scientific choice. Reflections
are rejected because they can change stereochemistry.

`species.identity` compares SpeciesRecords by isomeric graph, isotope, charge
and multiplicity. It does not resolve unspecified stereochemistry or classify
conformers. For geometric identity, use existing `artifact_compare` with suitable
mapping/stereochemical checks and physical tolerances.
