---
name: validation
description: Validate a transition-state candidate as a saddle point with the intended mode, structure, electronic state, and stereochemical assignment.
---

# ResearchAgent Transition-State Validation

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

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.

Read [transition_state_validation.md](references/transition_state_validation.md)
for saddle and mode evidence,
[connectivity_validation.md](references/connectivity_validation.md) for basin
identity criteria used after path calculations, and
[structure_validation.md](references/structure_validation.md) for mapping,
alignment, and stereochemical comparisons.


Registered validator: `job_start` with `validator_id="chemical.gaussian_frequency"`, a new `request_id`, and `input_artifact_ids=[<collected parsed.json artifact>]`. Its version is `1`. The runtime records actual execution and input digests. This checks normal termination and exactly one negative frequency only; mode character, geometry and IRC connectivity still require separate criteria.

Define forming/breaking bonds, atom transfers, or other coordinates from the
actual reaction hypothesis. Analyze collected primary outputs with suitable
scripts through generic Jobs; reaction-specific validator registration is not
required. Before selecting the bundled [specialized path validators](../candidate-generation/references/gaussian_path.md),
check their topology and input scope. Their criteria are not a universal
definition of a transition state.

Checks are scoped evidence, not a universal research gate. Distinguish tool execution failure, unreadable evidence and a completed check that did not satisfy its criterion. `parsing.status`, `scientific_verdict` (when supplied), and receipt `provenance` keep these separate. Job input/output digests establish recorded provenance; a solver title marker is an additional cross-check, not the sole provenance record. Unknown evidence does not prohibit a reasoned next experiment. Record the uncertainty and chosen method without claiming a pass.
