---
name: tspi-qbics
description: Assess whether a QBICS workflow is scientifically appropriate and discover whether a registered runnable capability exists before execution.
---

# TSPi QBICS

[Chinese version](SKILL.zh-CN.md)

Use this Skill when considering QBICS for crossing-point or related searches.
TSPi currently defines no public QBICS Backend capability, input contract, or
parser contract.

First query `research.read mode=capabilities capabilityKind=compute`. Proceed only
if the live catalog contains an exact QBICS capability and use its returned
roles and parameter schema. If none exists, describe the intended scientific
purpose, required electronic states, inputs, expected outputs, and validation
criteria as method guidance; do not invent a capability name, construct a
`compute.run` request, run arbitrary shell, or present QBICS as executable through
TSPi.

A future QBICS integration becomes runnable only after it has a deterministic
Backend adapter, immutable input preparation, declared outputs, parser contract,
task validation, and tests.
