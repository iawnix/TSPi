---
name: tspi-xtb
description: Run and interpret xTB and CREST calculations for conformers, geometry, frequencies, scans, molecular dynamics, and prescreening.
---

# TSPi xTB And CREST

[Chinese version](SKILL.zh-CN.md)

Use this Skill for xTB or CREST calculations. Load `tspi-orchestration` for
calculation, Artifact, and ResearchMap contracts, and
`tspi-transition-state-search` when choosing candidate generation.

Bind `xyz` and, for scans or MD, `control` inputs as logical Artifacts. Keep
method, charge, unpaired electrons, solvent, accuracy, and optimization level
in the calculation intent. Check SCC convergence, optimization status,
frequency data, scan completeness, and trajectory completeness as applicable.
Treat conformer count, energy table, and ensemble geometry as separate facts.
Record verified values as `FactFinding`; record missing outputs, failures, or
method limitations as `IssueFinding` when they affect the Node or Claim.

For remote work, select a configured environment with `ts_environment` or
`/compute`; a missing command or activation script is an operational failure,
not a reason to install software from the job. Read [xtb_executor.md](references/xtb_executor.md) and [crest_ensemble.md](references/crest_ensemble.md).
