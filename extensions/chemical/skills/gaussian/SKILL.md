---
name: gaussian
description: Prepare, run, and inspect Gaussian calculations from registered input files, including single-point, optimization, frequency, scan, transition-state, IRC, and QST workflows.
---

# TSPi Gaussian

[Chinese version](SKILL.zh-CN.md)

Use this Skill for Gaussian-specific input construction, execution, parsing,
and output checks. Method choice belongs to `method-selection`; scientific
TS assessment belongs to `validation`, and path meaning belongs to
`irc`.

Bind each `.gjf` input as a ResearchNode Artifact. Preserve route, method, basis,
charge, multiplicity, solvent, resources, task, and relevant keywords in the
immutable intent. Check that the output matches that intent, select the correct
job section, and assess termination, SCF behavior, optimization convergence,
frequency evidence, geometry, electronic state, IRC data, thermochemistry, and
scan profiles without conflating them. The Gaussian Route Section selects the
calculation mode; submit every supported mode to the registered `gaussian@1`
executor rather than registering `sp`, `freq`, `opt`, `irc`, or `scan` variants.

QST2/QST3 is expressed in the Gaussian Route Section and remains subject to
the input and output validation rules. Skills do not register capabilities;
the live Native catalog is authoritative for `gaussian@1`.

Gaussian methods such as HF and M062X, including basis notation such as
`6-31G**`, are expressed in the Route Section, for example
`# HF/6-31G** Opt` or `# M062X/6-31G SP`; they do not require one capability per
functional.

Record parser output only after checking primary files. Normal termination is
not task validation, and neither is a scientific verdict. Record SCF
instability, spin contamination, state ambiguity, missing corrections, and
method sensitivity explicitly. For an optimization-to-SP chain, use the
returned `optimized_input_artifact_id` and verify the Artifact type is
`chemical/gaussian-input`; the provider also exposes the final geometry as
`optimized_geometry_artifact_id`. Never pass stdout/stderr or a positional
entry from `artifact_ids` as a Gaussian input. Read
[gaussian_validation.md](references/gaussian_validation.md).
