---
name: irc
description: Plan and assess bidirectional intrinsic reaction coordinate calculations and assign their endpoints to declared molecular basins.
---

# TSPi IRC

[Chinese version](SKILL.zh-CN.md)

Use this Skill for forward/reverse IRC design, execution interpretation, path
completion, endpoint extraction, and endpoint identity. The Gaussian Skill
checks Gaussian-specific files; this Skill owns the chemical meaning of the
path.

For Gaussian, prepare the validated saddle checkpoint and declared path spec
with the `chemical.path-irc` Job executor, then execute each direction through
`chemical.gaussian-input`. Follow the [executable path workflow](../candidate-generation/references/gaussian_path.md)
for input preparation and evidence binding. Other mechanisms require an explicit
method and validated runner; the bundled path constructor covers its declared DA scope.

Start from a validated saddle candidate and preserve path direction. Check the
IRC origin against that structure, termination and path completeness in both
directions, final geometry and gradient, and whether endpoint optimization is
needed before basin assignment. Compare each endpoint with an explicit target
Artifact using mapping, key internal coordinates, stereochemistry, and a
deterministic structure comparison.

Record direction-specific path and endpoint facts separately. Missing or
contradictory endpoint evidence is an IssueFinding, but does not implicitly
change Node or Claim status. Read
[irc_validation.md](references/irc_validation.md).
