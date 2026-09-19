---
name: tspi-method-selection
description: Select a scientific method, registered Backend capability, and named local or remote compute environment for a bounded research question.
---

# TSPi Method Selection

[Chinese version](SKILL.zh-CN.md)

Use this Skill before execution when the method, Backend, capability, or compute
environment is not already fixed. Selection is a scientific decision; this
Skill does not launch work.

Start from the Finding needed to distinguish the relevant Claims. Consider
system size, charge, spin, electronic state, metals or multireference risk,
solvent, constraints, target observable, expected uncertainty, candidate
quality, and cost. Query the live compute capability and environment catalogs;
never infer availability from a Skill description. Select a named local or
remote environment whose Backend binding supports the exact capability and
parameters.

Use inexpensive exploration only when it answers a declared question. State
when a higher-level calculation, alternate method, or robustness check is
needed. Preserve the selected method and rationale in the Node and immutable
calculation intent.

## References

- [method_selection.md](references/method_selection.md): scientific criteria.
- [backend_contract.md](references/backend_contract.md): Backend and capability
  boundaries.
- [compute_environments.md](references/compute_environments.md): named local and
  remote environments, including remote Platform details.
- [runtime_environment.md](references/runtime_environment.md): installation-owned
  scientific runtime diagnosis.
