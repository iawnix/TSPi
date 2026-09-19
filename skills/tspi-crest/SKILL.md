---
name: tspi-crest
description: Run and assess CREST conformer searches and preserve ensemble membership, energies, settings, provenance, and selection rationale.
---

# TSPi CREST

[Chinese version](SKILL.zh-CN.md)

Use this Skill for the registered `crest.conformer_search` capability. CREST
owns ensemble exploration; xTB calculations outside a CREST search belong to
`tspi-xtb`.

Bind one XYZ Artifact and explicit charge, unpaired electrons, xTB method,
search and optimization levels, threads, and solvent settings. Validate normal
termination and the complete primary output set. Check that conformer and
energy-table counts agree and that each reused member preserves atom count,
order, and identity.

Record ensemble size, relative-energy table, selected geometry, and selection
rationale as distinct facts. A scheduler success with missing primary outputs
is an operational failure, not an empty ensemble. Read
[crest_ensemble.md](references/crest_ensemble.md).
