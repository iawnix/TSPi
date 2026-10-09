---
name: xtb
description: Run GFN2-xTB single-point and geometry optimization calculations for inexpensive structure screening.
---

# GFN2-xTB calculations

`chemical.xtb@1` uses the configured `xtb` command and wrapper environment.
Its executable tasks are `sp`, `opt`, and `opt-sp`.

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.xtb --version 1 --input geometry=input.xyz --output prepared/xtb.json -- --task opt-sp --charge 0 --multiplicity 1
```

Submit the returned request file/digest with `job_start` and the intended node_id.
Read the [runner contract](../method-selection/references/runner_results.md)
for output and electronic-state semantics. Multiplicity is converted to xTB's
unpaired-electron parameter inside the runner.

Check SCC and optimization convergence and retention of the intended molecular
structure. Use GFN2-xTB energies within a consistent method and state; their
absolute values are not an accuracy ranking against DFT energies. The bundled
executor does not implement frequency, scan or molecular-dynamics tasks.

See [xTB execution and interpretation](references/xtb_executor.md).
