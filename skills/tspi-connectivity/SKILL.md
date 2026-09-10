---
name: tspi-connectivity
description: Validate reaction-path endpoint assignments, atom mappings, stereochemistry, and molecular basin identity from explicit structural evidence.
---

# TSPi Connectivity

[Chinese version](SKILL.zh-CN.md)

Use this Skill when deciding whether a candidate path reaches the declared
reactant and product basins. Load `tspi-orchestration` for ProofSpec and
artifact contracts and `tspi-gaussian` for Gaussian output validation.

Connectivity is separate from stationary-point and imaginary-mode validation.
Finite IRC endpoints need basin assignment, and visual similarity or a low
global RMSD does not prove identity.

## Evidence Rules

- Preserve path direction and declare which endpoint is reactant or product.
- Inspect the last geometry and gradient; optimize an endpoint when necessary.
- Verify element counts, charge, multiplicity/state, isotopes when relevant,
  atom mapping, bond changes, internal coordinates, and stereochemistry.
- Use the versioned `connectivity` ProofSpec with explicit Observation refs.
  Missing direction, endpoint, path completion, or identity evidence remains
  inconclusive or creates a blocking Finding.
- Record mapping method, selected atoms, RMSD, key coordinates, source artifact
  digests, and limitations as semantic Observations.

Read `references/connectivity_validation.md` for the built-in connectivity
dimension and `references/ts_structures_contract.md` for deterministic
`ts_compare` parameters and structural identity rules.
