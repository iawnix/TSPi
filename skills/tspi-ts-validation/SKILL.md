---
name: tspi-ts-validation
description: Validate a transition-state candidate as a saddle point with the intended mode, structure, electronic state, and stereochemical assignment.
---

# TSPi Transition-State Validation

[Chinese version](SKILL.zh-CN.md)

Use this Skill to decide whether a candidate is a defensible transition-state
structure. Candidate generation and IRC endpoint assignment are separate
tasks.

Verify optimization and stationary-point evidence, exactly one relevant
imaginary mode for a classical first-order saddle, displacement along the
proposed bond changes, charge/multiplicity and electronic-state consistency,
atom mapping, geometry, and stereochemistry. Inspect the primary output and
mode vectors; normal termination or one negative frequency alone is
insufficient.

Record each verified property as a narrow FactFinding and each ambiguity,
missing check, competing mode, contamination, or structural mismatch as an
IssueFinding. Findings do not set Node or Claim status automatically. Use a
Gate only when explicit acceptance criteria need a recorded evaluation.

Read [transition_state_validation.md](references/transition_state_validation.md)
for saddle and mode evidence,
[connectivity_validation.md](references/connectivity_validation.md) for basin
identity criteria used after path calculations, and
[structure_validation.md](references/structure_validation.md) for mapping,
alignment, and stereochemical comparisons.
