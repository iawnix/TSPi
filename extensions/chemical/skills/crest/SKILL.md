---
name: crest
description: Run and assess CREST conformer searches and preserve ensemble membership, energies, settings, provenance, and selection rationale.
---

# TSPi CREST

[Chinese version](SKILL.zh-CN.md)

Use this Skill for CREST conformer searches through an installed command. CREST
owns ensemble exploration; xTB calculations outside a CREST search belong to
`xtb`.

This package has no bundled CREST runner. Inspect the selected environment's
command and documented options, then stage a generic `job_start` request if
available; a missing Skill script alone does not prove CREST is unavailable.

Do not treat a normal process exit or a non-empty ensemble as scientific
evidence until the primary files, member counts, and selected-structure
identity have been checked.

Bind one XYZ Artifact and explicit charge, unpaired electrons, xTB method,
search and optimization levels, threads, and solvent settings. Validate normal
termination and the complete primary output set. Check that conformer and
energy-table counts agree and that each reused member preserves atom count,
order, and identity.

Record ensemble size, relative-energy table, selected geometry, and selection
rationale as distinct facts. A scheduler success with missing primary outputs
is an operational failure, not an empty ensemble. Read
[crest_ensemble.md](references/crest_ensemble.md).
