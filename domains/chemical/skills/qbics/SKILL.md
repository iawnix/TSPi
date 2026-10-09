---
name: qbics
description: Assess QBICS applicability and verify an installed command, its inputs and validation needs before running a bounded research Job.
---

# ResearchAgent QBICS

[Chinese version](SKILL.zh-CN.md)

Use this Skill when considering QBICS for crossing-point or related searches.
The package does not bundle a QBICS preparation or parsing runner. This does
not determine whether a selected local or remote environment has QBICS installed.

Inspect the installation bindings and the installed program's documentation or
bounded help/version output. Verify its intended scientific task, electronic
states, input format, resources, required files and result interpretation.
If a usable command or shared runner exists, stage explicit inputs and invoke it
through generic `job_start`, preserving outputs and execution receipts. No
scientific workflow registry is required. Do not invent command-line options or
claim that a generic platform probe proves QBICS readiness.

If an execution or validation piece is missing, identify that concrete gap and
continue independent authorized work. Record unknown capability as unverified;
a missing script in this Skill alone is not an execution failure or scientific result.

For a task-specific wrapper, use the generic preparer with `--script` and an explicit `--backend`, as described in [method selection](../method-selection/SKILL.md). That path records scripts, environment, inputs and outputs. This Skill supplies scientific guidance; a bundled executable for this method is not currently provided.
