---
name: method-selection
description: Prepare a scientific method and named compute environment for execution, including when the user has already fixed the method.
---

# TSPi Method Selection

[Chinese version](SKILL.zh-CN.md)

Use this Skill when selecting a method or preparing execution for an already specified method. Read the relevant method Skill using its listed path. Installation configuration and method checks are Agent work; unavailable evidence is not automatically a request for user input.

Start from the requested observable or the scientific question to resolve. Consider
system size, charge, spin, electronic state, metals or multireference risk,
solvent, constraints, target observable, expected uncertainty, candidate
quality, and cost. Check the selected environment with `job_probe`; do not infer
software availability from a Skill description alone. Select a named local or
remote environment and let the Skill construct the exact command and parameters.

Use inexpensive exploration only when it answers a declared question. State
when a higher-level calculation, alternate method, or robustness check is
needed. Preserve the selected method and rationale in the Node and immutable
calculation intent.

For a requested optimization/single-point multi-method or multi-environment comparison, expand a complete
`method × environment × {opt, sp}` matrix before launching work, then probe
each environment and record independent failures for individual cells. The
execution entry comes from the installed extension inventory and its method Skill.
In this comparison, each `sp` depends on the `opt` output for the same method and
environment. Other studies may use explicitly chosen fixed geometries and TS/Freq/IRC/scan inputs; the Agent defines their dependencies. If one matrix
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

- [Request preparation](references/request_preparation.md): installed executors, explicit inputs and recovery.
- [Runner results, units and electronic state](references/runner_results.md)
