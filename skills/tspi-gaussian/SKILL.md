---
name: tspi-gaussian
description: Prepare, run, and inspect registered Gaussian single-point, optimization, frequency, transition-state, QST, and IRC calculations.
---

# TSPi Gaussian

[Chinese version](SKILL.zh-CN.md)

Use this Skill for Gaussian-specific input construction, execution, parsing,
and output checks. Method choice belongs to `tspi-method-selection`; scientific
TS assessment belongs to `tspi-ts-validation`, and path meaning belongs to
`tspi-irc`.

Bind each `.gjf` input as a Node-owned Artifact. Preserve route, method, basis,
charge, multiplicity, solvent, resources, task, and relevant keywords in the
immutable intent. Check that the output matches that intent, select the correct
job section, and assess termination, SCF behavior, optimization convergence,
frequency evidence, geometry, electronic state, IRC data, and thermochemistry
without conflating them.

Record parser output only after checking primary files. Normal termination is
not task validation, and neither is a scientific verdict. Record SCF
instability, spin contamination, state ambiguity, missing corrections, and
method sensitivity explicitly. Read
[gaussian_validation.md](references/gaussian_validation.md).
