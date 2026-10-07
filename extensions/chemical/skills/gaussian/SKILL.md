---
name: gaussian
description: Prepare, run, and inspect Gaussian calculations, including single-point, optimization, frequency, scan, transition-state, IRC, and QST workflows.
---

# Gaussian calculations

Use this Skill for gaussian tasks described above.

Use the installed [scripts/run.py](scripts/run.py) for input generation, execution and scientific validation. Read the target environment's `gaussian` command, activation_script and environment from installation `job.toml`. Local and remote bindings are distinct.

Generate a generic `job_start` request with the [preparation helper](../method-selection/scripts/prepare_job.py):

```text
python3 <method-selection>/scripts/prepare_job.py --config <job.toml> --environment <name> --backend gaussian --skill gaussian --xyz <input.xyz> -- --task opt-sp
```

Check method, basis, charge, spin and resources; add nodeId and timeoutSeconds before submitting. This helper only prepares a request. Stage both the Skill scripts and `_shared` directory with their relative layout intact. Activation runs in the target Job; no Provider registration is involved.

Run `run.py --help` for exact arguments. `--task opt-sp` explicitly optimizes then computes a single point on that geometry. Failure stops dependent steps and returns nonzero. `--spin` is 2S (Gaussian multiplicity=spin+1). XYZ coordinates are angstrom. Use a new empty output directory for every attempt.

Declare `results/result.json` and `results/geometry.xyz` as required outputs and collect raw step logs. Results preserve actual settings, input/geometry hashes, energy units, convergence evidence and script hashes. In addition to Job exit 0, verify `validated=true`, required steps and the optimization-to-SP geometry binding. Failed runs retain their result and logs; the last printed energy alone is insufficient.

Track via `job_status/job_collect/job_reconcile`; wait on the actual returned attempt_id. The Agent registers scientific Findings from evidence. Never silently change the method, basis or interpreter.

Defaults: M062X/6-31G**, Opt=Tight or SP, SCF=Tight, Int=UltraFine. Validate route readback, normal termination and optimization convergence. No frequency evidence means no verified minimum claim. This CLI does not yet orchestrate TS/IRC; historical parsing support is not end-to-end verification.

For detailed checks, read [gaussian_validation](references/gaussian_validation.md).
