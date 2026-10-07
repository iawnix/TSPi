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

Use [scripts/prepare_job.py](scripts/prepare_job.py) to generate the generic Job request from job.toml. Pass --config "$TS_JOB_CONFIG", --environment, --backend, --skill, --xyz, then -- followed by runner arguments. For remote xTB/Gaussian also provide --python with a configured target Python >=3.10, or set environment.python in job.toml. Do not assume python3 exists on the remote login PATH. Add nodeId/timeoutSeconds and verify the request before job_start. The helper stages complete script directories and `_shared` imports.

Preserve the prepared requestId when recovering the same submission. A lost tool response does not authorize a new ID; intentional recalculation uses a new request.
