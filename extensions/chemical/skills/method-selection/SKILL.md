---
name: method-selection
description: Select a scientific method, registered Backend workflow, and named local or remote compute environment for a bounded research question.
---

# TSPi Method Selection

[Chinese version](SKILL.zh-CN.md)

Use this Skill before execution when the method, Backend, workflow, or compute
environment is not already fixed. Selection is a scientific decision; this
Skill does not launch work.

Start from the Finding needed to distinguish the relevant Claims. Consider
system size, charge, spin, electronic state, metals or multireference risk,
solvent, constraints, target observable, expected uncertainty, candidate
quality, and cost. Query the live compute workflow and environment catalogs;
never infer availability from a Skill description. Select a named local or
remote environment whose Backend binding supports the exact workflow and
parameters.

Use inexpensive exploration only when it answers a declared question. State
when a higher-level calculation, alternate method, or robustness check is
needed. Preserve the selected method and rationale in the Node and immutable
calculation intent.

For a multi-method or multi-environment comparison, expand a complete
`method × environment × {opt, sp}` matrix before launching work, then query
the exact workflow and readiness for every cell. The first-party routing
rules are:

| Method | Provider | Capability |
| --- | --- | --- |
| CF22D | PySCF | `pyscf.opt` / `pyscf.sp` |
| GFN1-xTB, GFN2-xTB | xTB | `xtb.opt` / `xtb.sp` |
| HF, M062X, and other Gaussian Route Section methods | Gaussian | `gaussian` |

Gaussian methods and basis sets belong in the `.gjf` Route Section, for
example `# M062X/6-31G Opt` or `# HF/6-31G** SP`. A missing functional in the
PySCF descriptor does not make a Gaussian route unavailable. Every `sp` job
depends on the `opt` output for the same method and environment. If one matrix
cell is unavailable, block that cell explicitly; do not silently substitute a
method or stop independent cells.

## References

- [method_selection.md](references/method_selection.md): scientific criteria.
- [backend_contract.md](references/backend_contract.md): Backend and workflow
  boundaries.
- [job_probes.md](references/job_probes.md): named local and
  remote environments, including remote Platform details.
- [runtime_environment.md](references/runtime_environment.md): installation-owned
  scientific runtime diagnosis.
