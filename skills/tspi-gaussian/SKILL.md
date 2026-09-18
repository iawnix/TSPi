---
name: tspi-gaussian
description: Prepare and assess Gaussian single-point, optimization, frequency, and IRC calculations with Node-owned artifacts and Findings.
---

# TSPi Gaussian

[Chinese version](SKILL.zh-CN.md)

Use this Skill for Gaussian input preparation and output validation. Load
`tspi-orchestration` for ResearchMap and calculation contracts; load
`tspi-connectivity` when an IRC result assigns endpoint identity.

Bind the input as a `gjf` Artifact and preserve method, basis, charge,
multiplicity, environment, resources, and relevant keywords in the calculation
intent. Check normal termination and agreement with that intent. Inspect
optimization convergence, frequency count, mode assignment, IRC path,
electronic state, and thermochemistry separately.

For a first-order saddle, verify one imaginary frequency, relate its displacement
to the proposed step, and establish endpoint connectivity. Record verified
values as `FactFinding`; record SCF instability, spin contamination, state
ambiguity, warnings, or method sensitivity as `IssueFinding`. Cite the primary
output Artifact and keep each Finding narrow.

Read [gaussian_validation.md](references/gaussian_validation.md) for the
method-specific checklist. Candidate generation belongs to
`tspi-transition-state-search`; endpoint assignment belongs to
`tspi-connectivity`.
