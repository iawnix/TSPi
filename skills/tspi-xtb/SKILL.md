---
name: tspi-xtb
description: Run and assess registered xTB single-point, optimization, frequency, scan, molecular-dynamics, and prescreening calculations.
---

# TSPi xTB

[Chinese version](SKILL.zh-CN.md)

Use this Skill for registered xTB capabilities. CREST conformer searches belong
to `tspi-crest`; selecting xTB instead of another method belongs to
`tspi-method-selection`.

Bind XYZ and, for scans or molecular dynamics, control inputs as logical
Artifacts. Keep method, charge, unpaired electrons, solvent model, accuracy,
optimization settings, and constraints explicit in the calculation intent.
Check SCC convergence, optimization status, frequency data, scan completeness,
and trajectory completeness as appropriate.

Treat an optimized geometry, energy, frequency set, scan series, and trajectory
as separate results. Inspect primary outputs before recording Findings. A scan
maximum or xTB imaginary mode is a candidate for further validation, not proof
of a transition state. Read [xtb_executor.md](references/xtb_executor.md).
