---
name: gaussian
description: Prepare, run, and inspect Gaussian calculations, including single-point, optimization, frequency, scan, transition-state, IRC, and QST workflows.
---

# Gaussian calculations

Use this Skill for gaussian tasks described above.

Use the installed [scripts/run.py](scripts/run.py) for input generation, execution and scientific validation. Read the target environment's `gaussian` command, activation_script and environment from installation `job.toml`. Local and remote bindings are distinct.

Generate a generic `job_start` request with the [preparation helper](../method-selection/scripts/prepare_job.py):

```text
"$TSPI_PYTHON" <method-selection>/scripts/prepare_job.py --config <job.toml> --environment <name> --backend gaussian --skill gaussian --xyz <input.xyz> -- --task opt-sp
```

Check method, basis, charge, spin and resources; add node_id and timeout_seconds before submitting. This helper only prepares a request. Stage both the Skill scripts and `_shared` directory with their relative layout intact. Activation runs in the target Job; no Provider registration is involved.

Run `run.py --help` for exact arguments. `--task opt-sp` explicitly optimizes then computes a single point on that geometry. Failure stops dependent steps and returns nonzero. `--spin` is 2S (Gaussian multiplicity=spin+1). XYZ coordinates are angstrom. Use a new empty output directory for every attempt.

Declare `results/result.json` and `results/geometry.xyz` as required outputs and collect raw step logs. Results preserve actual settings, input/geometry hashes, energy units, convergence evidence and script hashes. In addition to Job exit 0, verify `validated=true`, required steps and the optimization-to-SP geometry binding. Failed runs retain their result and logs; the last printed energy alone is insufficient.

Track via `job_status/job_collect/job_reconcile`; wait on the actual returned attempt_id. The Agent registers scientific Findings from evidence. Never silently change the method, basis or interpreter.

Defaults: M062X/6-31G**, Opt=Tight or SP, SCF=Tight, Int=UltraFine. Validate route readback, normal termination and optimization convergence. No frequency evidence means no verified minimum claim. The Agent chooses the sequence of TS, frequency, IRC and endpoint calculations using the explicit-input interface below.

For detailed checks, read [gaussian_validation](references/gaussian_validation.md).

Python dependencies are installation-owned Conda environments configured in job.toml. Run preparation helpers with "$TSPI_PYTHON"; target runners use the resolved Conda binding. Missing environments require installation maintenance, not ad-hoc pip installs during a research turn.

## Explicit Gaussian inputs

For TS/Freq/IRC/QST/scan, prepare a complete .gjf in the workspace. Use the
method-selection helper with --input-gjf instead of --xyz. After -- pass
--method, --basis, --charge, --spin, --threads, --memory-mb, and --validation.
Every Link1 section must declare the requested method/basis, %nprocshared and
%mem. Charge/multiplicity headers must agree; Geom=AllCheck inherits them from
checkpoint evidence, which the Agent must verify. Supply dependencies with
--dependency /absolute/source.chk=previous.chk before --. File references must
be relative staged paths. --collect ts.chk preserves results/ts.chk for later Jobs.

```text
"$TSPI_PYTHON" <method-selection>/scripts/prepare_job.py --config "$TS_JOB_CONFIG" --environment local --backend gaussian --skill gaussian --input-gjf ts.gjf --collect ts.chk --output prepared/ts.json -- --method M062X --basis '6-31G**' --charge 0 --spin 0 --threads 12 --memory-mb 4000 --validation saddle
```

Use --validation opt/sp/frequency/minimum/saddle/irc/none for deterministic checks.
saddle checks stationary-point convergence and one imaginary frequency; the
Agent must still inspect the mode direction. IRC emits path points and endpoint
artifacts; its basin assignment and completeness require interpretation.
Raw-input results separate execution_succeeded, normal_termination, checks_passed
and scientific_validation. They remain validated=false until scientific evidence
is interpreted in Research State; do not rewrite result.json to promote a result.
Normal termination alone does not prove a minimum, TS, or reaction mechanism.
Keep raw logs/checkpoints. Plan branches, retries and stopping in research_strategy;
this helper runs one supplied input rather than choosing the next experiment.
