---
name: chemical-input
description: Turn chemical names, descriptions or supplied structures into molecular graphs and initial geometries using PubChem/OPSIN lookup, Agent inference and structure checks; prepare explicit reaction mappings when needed.
---

# Chemical input

[Chinese version](SKILL.zh-CN.md)

Use this Skill to prepare structures for the user's research. Keep the original
input, chosen structure, source, charge and multiplicity with the resulting files.

## From input to calculation

1. Use an explicitly supplied structure, such as SMILES, directly. For a name,
   try PubChem then OPSIN using `chemical.resolve@1` (an explicit installation
   resolver preference takes priority). Preserve the original name; use
   `--lookup-name` for a translated or normalized query when useful.
2. When lookup yields no usable structure, including unavailable services or
   missing configuration, infer candidate SMILES from the user's description.
   The current Agent performs this reasoning. Write candidates with `source=llm`,
   a short rationale and relevant assumptions, then run `chemical.resolve-candidates@1`.
   This local step checks the proposals without repeating the network lookup.
3. Use structure checks to repair parsing, valence, charge or multiplicity errors.
   With multiple plausible structures, select and explain a working choice or
   study separate branches within the task's scope. Enumerate unspecified stereo
   when appropriate. Ask only when missing information prevents choosing a useful
   research approach; a lookup failure alone should lead to inference.
4. Generate initial geometries with `chemical.seed@1`, then continue the requested
   optimization, single-point or reaction work. Candidate source is provenance;
   it does not impose a confirmation step before subsequent calculations.

Prepare each entry with the generic executor CLI and submit its returned file and
digest through `job_start`. The selected target's `structure` Python binding
provides RDKit. Collect the Job's JSON and geometries as research materials.

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.resolve --version 1 --output prepared/lookup.json -- --name 'ethanol'
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.resolve-candidates --version 1 --input candidates=inputs/candidates.json --output prepared/candidates.json
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.seed --version 1 --output prepared/seed.json -- --smiles CCO --charge 0 --multiplicity 1
```

Use `chemical.inspect@1` for supplied or revised SMILES when graph checks are needed.
Avoid repeating checks already present in a collected candidate result. An initial
geometry is the starting point for the requested calculations; report computed
results after inspecting their outputs.

## Reactions and comparison

Use `chemical.reaction@1` when the task needs reactant/product atom mapping. Check
composition, charge and explicit mappings, and supply the intended bond changes
with `--transformation`. These steps apply to reaction work; a single-molecule
optimization or single-point calculation needs no reaction mapping.

Retain the chosen target structure as an Artifact and use `chemical.compare@1` to
compare a calculated structure with it when the study calls for that check. Cite
checks and source structures in the research record and explain relevant differences.

## References

- [name_resolution.md](references/name_resolution.md): lookup, inference input and result fields.
- [structure_input.md](references/structure_input.md): graph checks, geometries and structure comparison.
- [reaction_mapping.md](references/reaction_mapping.md): atom mapping and reaction graph checks.
