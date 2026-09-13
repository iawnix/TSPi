---
name: tspi-qbics
description: Plan and assess QBICS DMECP electronic-state crossing calculations with explicit configuration and state-character evidence.
---

# TSPi QBICS / DMECP

[Chinese version](SKILL.zh-CN.md)

Use this Skill for the registered `qbics.dmecp` capability. Load
`tspi-orchestration` for task, artifact, and state contracts. Load
`tspi-transition-state-search` only when a crossing candidate is part of a
larger candidate-generation strategy.

QBICS/DMECP addresses an electronic-state crossing problem. Treat its output as
a crossing candidate until the relevant state identities, energies, geometry,
and physical interpretation are verified. Choose validation criteria for the
electronic-state crossing being studied.

## Operating Rules

- Bind exactly one QBICS configuration artifact to the calculation intent.
- Preserve state labels, charge, multiplicity, method, and convergence settings
  in the configuration and Node rationale.
- Check both expected primary outputs: `dmecp_candidate.xyz` and
  `dmecp_summary.json`, along with program status and parser evidence.
- Record state-character, crossing geometry, energy gap, gradients, and method
  limitations as separate Observations or Findings when the output supports
  them. Missing state evidence remains inconclusive.
- Use registered electronic-structure or state-character ProofSpecs appropriate
  to the Claim. Record a validation gap when the required checks are unavailable.

Use the capability descriptor for accepted inputs and remote diagnostics for
software readiness. Relate the verified crossing to the research hypothesis.
