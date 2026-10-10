---
name: cf22d
description: Run and interpret PySCF CF22D single-point, geometry optimization, transition-state, frequency, and RRHO thermochemistry calculations.
---

# CF22D calculations

Use `chemical.cf22d@1` with the target's `pyscf` binding. The executor supports
`sp`, `opt`, `opt-sp`, `ts`, `freq`, `thermo`, `opt_freq`, and `ts_freq`.
CF22D and its dispersion implementation must be available in that environment.

```bash
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.cf22d --version 1 --input geometry=input.xyz --output prepared/cf22d.json -- --task opt-sp --basis def2-tzvp --charge 0 --multiplicity 1
```

Submit the returned request file/digest with `job_start` and the intended node_id.
Preparation stages the declared scripts and outputs. Read the shared
[runner contract](../method-selection/references/runner_results.md) for result,
unit, electronic-state and optimization-to-SP semantics.

Choose the basis and resources for the user's question; the default basis is
`def2-tzvp`. Inspect SCF and optimization convergence, frequency modes and the
limitations of RRHO corrections before interpreting a stationary point or free
energy. A TS optimization alone does not establish the target reaction.

- [Scientific checks and method limits](references/cf22d_workflow.md)
- [Target environment diagnosis](references/environment_doctor.md)
