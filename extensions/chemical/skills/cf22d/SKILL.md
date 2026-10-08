---
name: cf22d
description: Plan, diagnose, and run PySCF CF22D single-structure calculations for SCF, optimization, transition-state, frequency, and RRHO thermochemistry tasks.
---

# CF22D calculations

Use this Skill for cf22d tasks described above.

Use the installed [scripts/run.py](scripts/run.py) for input generation, execution and scientific validation. Read the target environment's `pyscf.python` Conda binding, activation_script and environment from installation `job.toml`. Local and remote bindings are distinct.

Generate a generic `job_start` request with the [preparation helper](../method-selection/scripts/prepare_job.py):

```text
"$TSPI_PYTHON" <method-selection>/scripts/prepare_job.py --config <job.toml> --environment <name> --backend pyscf --skill cf22d --xyz <input.xyz> -- --task opt-sp
```

Check method, basis, charge, spin and resources; add node_id and timeout_seconds before submitting. This helper only prepares a request. Stage both the Skill scripts and `_shared` directory with their relative layout intact. Activation runs in the target Job; no Provider registration is involved.

Run `run.py --help` for exact arguments. `--task opt-sp` explicitly optimizes then computes a single point on that geometry. Failure stops dependent steps and returns nonzero. `--spin` is 2S (Gaussian multiplicity=spin+1). XYZ coordinates are angstrom. Use a new empty output directory for every attempt.

Declare `results/result.json` and `results/geometry.xyz` as required outputs and collect raw step logs. Results preserve actual settings, input/geometry hashes, energy units, convergence evidence and script hashes. In addition to Job exit 0, verify `validated=true`, required steps and the optimization-to-SP geometry binding. Failed runs retain their result and logs; the last printed energy alone is insufficient.

Track via `job_status/job_collect/job_reconcile`; wait on the actual returned attempt_id. The Agent registers scientific Findings from evidence. Never silently change the method, basis or interpreter.

Also supports sp, opt, ts, freq, thermo, opt_freq and ts_freq. CF22D/D3 availability and optimization convergence are checked. RHF is not a substitute. For t006 pass `--basis 6-31G**`. See [scientific boundaries](references/cf22d_workflow.md).

For detailed checks, read [environment_doctor](references/environment_doctor.md).

Python dependencies are installation-owned Conda environments configured in job.toml. Run preparation helpers with "$TSPI_PYTHON"; target runners use the resolved Conda binding. Missing environments require installation maintenance, not ad-hoc pip installs during a research turn.
