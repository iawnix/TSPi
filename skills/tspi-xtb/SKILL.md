---
name: tspi-xtb
description: Run and interpret xTB and CREST calculations for conformers, geometry, frequencies, scans, molecular dynamics, and prescreening.
---

# TSPi xTB And CREST

[Chinese version](SKILL.zh-CN.md)

Use this Skill for xTB or CREST calculations. Load `tspi-orchestration` for
calculation, artifact, and state contracts. Load `tspi-transition-state-search`
when the task is choosing a candidate-generation strategy.

xTB provides approximate electronic-structure calculations for exploration and
characterization. CREST supplies conformer ensembles through an xTB-based
search. Assess transition-state and mechanism Claims using stationary-point,
mode, and connectivity evidence at the chosen level of theory.

## Operating Rules

- Bind `xyz` and, for xTB scan/MD, `control` inputs as logical artifacts.
- Choose method, charge, unpaired electrons, solvent model, accuracy, and
  optimization level as part of the scientific intent. Record changes to these
  settings as a recalculation with an updated intent.
- Check the required output set and parser summary, including SCC convergence
  when applicable, optimization status, frequency data, scan completeness, or
  trajectory completeness.
- Before remote xTB or CREST submission, require the configured software profile
  to pass `TSPi --check-remote`. Treat a missing command, activation script, or
  runtime dependency as an operational failure; do not install or repair cluster
  software from a calculation job.
- Treat conformer count, energy table, and ensemble geometry as separate facts.
  Select a conformer through a stated Claim or Node rationale.
- Promote only verified parser values and primary artifacts through `ts_change`.

## References

- Executor inputs, settings, and artifacts: [xtb_executor.md](references/xtb_executor.md)
- CREST ensemble checks: [crest_ensemble.md](references/crest_ensemble.md)
