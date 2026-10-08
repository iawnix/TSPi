---
name: chemical-input
description: Resolve chemical names, inspect molecular graphs, generate reproducible initial geometries, and validate explicit reaction mappings with executable helpers.
---

# Chemical input

[Chinese version](SKILL.zh-CN.md)

Use this Skill for names, SMILES, structure descriptions, or reaction inputs.
Use [scripts/prepare.py](scripts/prepare.py) through bash with "$TSPI_PYTHON".
It requires the installation-owned RDKit environment. Preserve original names,
structure sources, charge, multiplicity, and the helper JSON as evidence.

For a single molecule, resolve its identity and inspect its graph before seed
preparation. No reaction mapping is required for a molecular optimization or SP.
The helper has an explicit neutral-water rule (water/H2O/水/水分子 → O).
Other names use configured PubChem/OPSIN; --lookup-name preserves the original
name while supplying a translated or normalized lookup. Do not infer name
identity merely because an LLM-proposed SMILES passes graph validation.
User-supplied structures can be inspected directly without name lookup.

```text
"$TSPI_PYTHON" <chemical-input>/scripts/prepare.py --output identity.json resolve --name water
"$TSPI_PYTHON" <chemical-input>/scripts/prepare.py --output graph.json inspect --smiles O
"$TSPI_PYTHON" <chemical-input>/scripts/prepare.py --output seed.json seed --smiles O --charge 0 --multiplicity 1 --output-dir seeds
```

For reactions, resolve/inspect each species, then check composition, charge,
explicit atom mapping with the reaction subcommand, which lists bond changes.
Outputs use `chemical-reaction/2` with scoped `checks`, not a global validated flag.
Without `--transformation <JSON>`, the intended bond-change pattern is not assessed.
A declared `diels_alder` template checks the full changed-bond pattern, preserved
substituents and per-atom H counts; `explicit` supports other declared bond/H changes.
Map explicit hydrogens for proton-transfer studies.

```text
"$TSPI_PYTHON" <chemical-input>/scripts/prepare.py --output reaction.json reaction --smiles '<mapped-reactants>><mapped-products>'
```

An unresolved name or genuinely different identities needs a bounded lookup or
clarification. Unspecified stereochemistry may instead define the authorized
research scope: seed --enumerate-stereo enumerates up to 16 alternatives and
records each one. Keep alternatives explicit; do not silently select one.
A generated seed is not an optimized geometry, TS, or proof of connectivity.
Use separate calculations to explore conformers and intermolecular approaches.

## References

- [name_resolution.md](references/name_resolution.md): lookup, configuration and provenance.
- [structure_input.md](references/structure_input.md): graph, seed and reaction checks.
