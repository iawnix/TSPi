---
name: tspi-xtb
description: Use xTB and CREST for bounded conformer, geometry, frequency, scan, molecular-dynamics, and prescreening tasks with explicit evidence limits.
---

# TSPi xTB And CREST

[Chinese version](SKILL.zh-CN.md)

Use this Skill for xTB or CREST calculations. Load `tspi-orchestration` for
calculation, artifact, and state contracts. Load `tspi-transition-state-search`
when the task is choosing a candidate-generation strategy.

xTB is an approximate executor for bounded exploration and characterization.
CREST supplies conformer ensembles through an xTB-based search. Neither a
normal termination marker, a low energy, nor an optimized geometry proves a
classical transition state or a reaction mechanism.

## Operating Rules

- Bind `xyz` and, for xTB scan/MD, `control` inputs as logical artifacts.
- Choose method, charge, unpaired electrons, solvent model, accuracy, and
  optimization level as part of the scientific intent; do not silently change
  them in a retry.
- Check the required output set and parser summary, including SCC convergence
  when applicable, optimization status, frequency data, scan completeness, or
  trajectory completeness.
- Treat conformer count, energy table, and ensemble geometry as separate facts.
  Select a conformer through a stated Claim or Node rationale.
- Promote only verified parser values and primary artifacts through `ts_change`.

## References

- Executor inputs, settings, and artifacts: `references/xtb_executor.md`
- CREST ensemble checks: `references/crest_ensemble.md`
