---
name: tspi-connectivity
description: Validate reaction-path endpoint assignments, atom mappings, stereochemistry, and molecular basin identity from structural evidence.
---

# TSPi Connectivity

[Chinese version](SKILL.zh-CN.md)

Use this Skill when deciding whether a candidate path reaches the declared
reactant and product basins. Load `tspi-orchestration` for map and Artifact
contracts and `tspi-gaussian` for output checks.

Preserve path direction and identify each endpoint. Inspect the last geometry
and gradient, optimizing an endpoint when needed. Verify element counts, charge,
multiplicity, isotopes, atom mapping, bond changes, internal coordinates, and
stereochemistry. Use `ts_compare` for deterministic structure comparisons.

Record verified endpoint identity, mapping, RMSD, key coordinates, and source
Artifact references as `FactFinding`. Missing direction, endpoint, path
completion, or identity evidence is an `IssueFinding` and keeps the Claim or
Node inconclusive until resolved. Use a ClaimGate or NodeGate only when an
explicit criterion needs a visible evaluation; do not invent a separate proof
protocol.

Read [connectivity_validation.md](references/connectivity_validation.md) and
[ts_structures_contract.md](references/ts_structures_contract.md) for the
deterministic checklist and comparison parameters.
