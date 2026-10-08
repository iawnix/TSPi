---
name: energetics
description: Evaluate electronic energies, ZPE and thermal corrections, free and reaction energies, barriers, bounded TST rates, and energy profiles.
---

# TSPi Energetics

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `E`, `E+ZPE`, `H`, `G`, reaction and activation energies,
standard-state corrections, bounded transition-state-theory rates, and energy
profiles. Keep quantity, units, temperature, pressure or concentration,
standard state, phase, solvent, method, electronic state, stoichiometry, and
frequency treatment explicit.

Do not combine electronic and thermal results unless structures, atom order,
methods, and declared composite treatment are compatible. Do not use an
electronic barrier as a Gibbs barrier, infer unsupported isotope corrections,
or treat a qualitative pathway enumeration as kinetics. Record values and
limitations as separate Findings with source Artifacts.

Read [energetics.md](references/energetics.md) for scientific checks and execution
limits. This Skill does not provide callable thermochemistry, kinetics or network
analysis tools; execute a concrete analysis and preserve its evidence before recording results.
