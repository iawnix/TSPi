---
name: tspi-gaussian
description: Prepare and assess Gaussian single-point, optimization, frequency, and IRC calculations with intent-bound output evidence.
---

# TSPi Gaussian

[Chinese version](SKILL.zh-CN.md)

Use this Skill for Gaussian input preparation and output validation. Load
`tspi-orchestration` for calculation and evidence contracts. Load
`tspi-connectivity` when an IRC result is used to assign endpoint identity.

## Evidence Rules

- Bind the Gaussian input as a `gjf` logical artifact and keep route, method,
  basis, charge, multiplicity, environment, resources, and relevant keywords
  in the immutable intent.
- Check the primary output for normal termination and agreement with the intent.
- Keep optimization convergence, frequency count, mode assignment, IRC path,
  electronic-state concerns, and thermochemistry as separate Observations.
- For an ordinary first-order saddle, verify one imaginary frequency, assign
  its displacement to the proposed reaction step, and establish endpoint
  connectivity. Assess thermochemistry using its own corrections and conditions.
- Record SCF instability, spin contamination, state ambiguity, warnings, and
  method sensitivity as Findings or explicit Observations.

## Focused Reference

Read [gaussian_validation.md](references/gaussian_validation.md) for the validation dimensions and
versioned ProofSpec guidance. QST and other candidate strategies belong to
`tspi-transition-state-search`; endpoint assignment belongs to
`tspi-connectivity`.
