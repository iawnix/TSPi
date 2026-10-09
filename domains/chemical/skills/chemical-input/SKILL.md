---
name: chemical-input
description: Resolve chemical names, inspect molecular graphs, generate reproducible initial geometries, and validate explicit reaction mappings with executable helpers.
---

# Chemical input

[Chinese version](SKILL.zh-CN.md)

Use this Skill for names, SMILES, structure descriptions, or reaction inputs.
Prepare the declared `chemical.resolve`, `chemical.inspect`, `chemical.seed` or
`chemical.reaction` entry, version `1`, then execute its file through `job_start`.
These use the selected target's `structure` Python binding with RDKit. Preserve original names,
structure sources, charge, multiplicity, and the helper JSON as evidence.

For a single molecule, resolve its identity and inspect its graph before seed
preparation. No reaction mapping is required for a molecular optimization or SP.
The helper has an explicit neutral-water rule (water/H2O/水/水分子 → O).
Other names use configured PubChem/OPSIN; --lookup-name preserves the original
name while supplying a translated or normalized lookup. Do not infer name
identity merely because an LLM-proposed SMILES passes graph validation.
User-supplied structures can be inspected directly without name lookup.

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.resolve --version 1 --output prepared/identity.json -- --name water
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.inspect --version 1 --output prepared/graph.json -- --smiles O
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.seed --version 1 --output prepared/seed.json -- --smiles O --charge 0 --multiplicity 1
```

Each command only prepares a request. Submit the returned file/digest with the
returned digest, then collect the Job. Generated structures and JSON retain the
Job and selected binding; a seed Job collects every generated XYZ.

For reactions, resolve/inspect each species, then check composition, charge,
explicit atom mapping with the reaction subcommand, which lists bond changes.
Outputs use `chemical-reaction/2` with scoped `checks`, not a global validated flag.
Without `--transformation <JSON>`, the intended bond-change pattern is not assessed.
A declared `diels_alder` template checks the full changed-bond pattern, preserved
substituents and per-atom H counts; `explicit` supports other declared bond/H changes.
Map explicit hydrogens for proton-transfer studies.

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.reaction --version 1 --output prepared/reaction.json -- --smiles '<mapped-reactants>><mapped-products>'
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

- [reaction_mapping.md](references/reaction_mapping.md): Atom mapping and reaction graph checks.

## Compare target and calculated identity

`chemical.inspect` and `chemical.seed` include a versioned `chemical-identity/1` object: canonical isomeric SMILES, charge, RDKit version and content identity. Preserve the inspected target as an Artifact and refer to it through the Node's `subjects.target`. A filename such as product.xyz does not establish target identity.

Use `chemical.compare@1` with `--input target=<inspect.json>` and `--input actual=<structure.json-or-geometry.xyz>`. The prepared Job's input roles pin both source digests. For XYZ pass `-- --actual-format xyz --charge <actual-charge>`; structure JSON is the default. Collect `results/comparison.json`. It reports match, mismatch or indeterminate, the target and actual identities and its scope. Geometry bond orders are explicitly inferred; unresolved stereochemistry remains indeterminate. Cite the collected comparison as `check_refs` and distinguish target/calculated subjects in the Result. Checks support interpretation; they do not gate publication or further experiments.
