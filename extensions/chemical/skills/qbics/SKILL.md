---
name: qbics
description: Assess whether a QBICS workflow is scientifically appropriate and discover whether a registered runnable workflow exists before execution.
---

# TSPi QBICS

[Chinese version](SKILL.zh-CN.md)

Use this Skill when considering QBICS for crossing-point or related searches.
TSPi currently defines no public QBICS Backend workflow, input contract, or
parser contract.

First query `read the relevant Skill references and use job_probe for environment checks`. Proceed only
if the live catalog contains an exact QBICS workflow and use its returned
roles and parameter schema. If none exists, describe the intended scientific
purpose, required electronic states, inputs, expected outputs, and validation
criteria as method guidance; do not invent a workflow name, construct a
`job_start` request, run arbitrary shell, or present QBICS as executable through
TSPi.

A future QBICS integration becomes runnable only after it has a deterministic
Backend adapter, immutable input preparation, declared outputs, parser contract,
task validation, and tests.
