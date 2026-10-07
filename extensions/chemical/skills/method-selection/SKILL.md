---
name: method-selection
description: Prepare a scientific method and named compute environment for execution, including when the user has already fixed the method.
---

# TSPi Method Selection

[Chinese version](SKILL.zh-CN.md)

Use this Skill when selecting a method or preparing execution for an already specified method. Read the relevant method Skill using its listed path. Installation configuration and method checks are Agent work; unavailable evidence is not automatically a request for user input.

Start from the Finding needed to distinguish the relevant Claims. Consider
system size, charge, spin, electronic state, metals or multireference risk,
solvent, constraints, target observable, expected uncertainty, candidate
quality, and cost. Check the selected environment with `job_probe`; do not infer
software availability from a Skill description alone. Select a named local or
remote environment and let the Skill construct the exact command and parameters.

Use inexpensive exploration only when it answers a declared question. State
when a higher-level calculation, alternate method, or robustness check is
needed. Preserve the selected method and rationale in the Node and immutable
calculation intent.

For a multi-method or multi-environment comparison, expand a complete
`method × environment × {opt, sp}` matrix before launching work, then probe
each environment and record independent failures for individual cells. The
first-party routing rules are:

| Method | Program | Job command |
| --- | --- | --- |
| CF22D | PySCF | cf22d/scripts/run.py |
| GFN2-xTB | xTB | `xtb` optimization / single point |
| HF, M062X, and other Gaussian Route Section methods | Gaussian | `g16` with the `.gjf` Route Section |

Gaussian methods and basis sets belong in the `.gjf` Route Section, for
example `# M062X/6-31G** Opt` or `# HF/6-31G** SP`. Every `sp` job
depends on the `opt` output for the same method and environment. If one matrix
cell is unavailable, block that cell explicitly; do not silently substitute a
method or stop independent cells.

## References

- [method_selection.md](references/method_selection.md): scientific criteria.
- [backend_contract.md](references/backend_contract.md): scientific Job contract
  and execution boundary.
- [job_probes.md](references/job_probes.md): named local and
  remote environments, including remote Platform details.
- [runtime_environment.md](references/runtime_environment.md): installation-owned
  scientific runtime diagnosis.

## Executable request preparation

Use [scripts/prepare_job.py](scripts/prepare_job.py) to generate the generic Job request from job.toml. Pass --config "$TS_JOB_CONFIG", --environment, --backend, --skill, --xyz, then -- followed by runner arguments. Use the installation TSPI_PYTHON to run this preparation helper. The public job_runtime.config_contract resolves structured Conda bindings from job.toml: backend.python overrides environment.python. Remote scripts run with the configured conda_executable and prefix; do not guess Python or pass --python. CF22D uses backends.pyscf.python without a second Python command binding. Add nodeId/timeoutSeconds and verify the request before job_start. The helper stages complete script directories and `_shared` imports.

Preserve the prepared requestId when recovering the same submission. A lost tool response does not authorize a new ID; intentional recalculation uses a new request.

Python dependencies are installation-owned Conda environments configured in job.toml. Run preparation helpers with "$TSPI_PYTHON"; target runners use the resolved Conda binding. Missing environments require installation maintenance, not ad-hoc pip installs during a research turn.


Save helper output with `--output <workspace>/prepared/<cell>.json` (before `--`).
The helper prints `requestFile` and `requestSha256`; pass these unchanged to
`job_start`, adding only `nodeId` and optional `timeoutSeconds`. Do not copy
individual command/input fields. Inspect the file if needed; changing it requires
recomputing its digest. Repeated preparation of identical inputs/configuration
preserves workId/requestId. Use `--work-id` only for intentional new work.

Remote preparation requires an explicit `submission.queue` in the environment
or backend's job.toml table. `submission.resources` supplies CPU/memory/walltime;
backend fields override environment defaults. An allowlist does not choose a
queue. Missing queue configuration needs installation maintenance. Inspect
job_status diagnostics when a queue-wait event arrives; no exit receipt while
queued/running is normal. Do not resubmit or change queues without reconciling
the original Job. An optional `submission.queue_wait_seconds` causes one Monitor
notification when that waiting threshold is exceeded.
