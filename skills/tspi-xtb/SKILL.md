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
of a transition state. When chaining an optimization into a single point, use
the returned `calculation.optimized_geometry_artifact_id` (also listed under
the `optimized_geometry` artifact role) and verify the Artifact type
is `chemical/xyz`; never choose a stdout/stderr ID by position. Read
[xtb_executor.md](references/xtb_executor.md).
