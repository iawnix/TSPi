---
name: irc
description: Plan and assess bidirectional intrinsic reaction coordinate calculations and assign their endpoints to declared molecular basins.
---

# CoRAgent IRC

[Chinese version](SKILL.zh-CN.md)

Use this Skill for forward/reverse IRC design, execution interpretation, path
completion, endpoint extraction, and endpoint identity. The Gaussian Skill
checks Gaussian-specific files; this Skill owns the chemical meaning of the
path.

For Gaussian, prepare forward and reverse IRC inputs from the saddle geometry
or checkpoint, preserving method, basis, charge, and electronic state. Select
options for the actual Hessian source, then execute with `chemical.gaussian-input`
or a generic Job. The [specialized path preparer](../candidate-generation/references/gaussian_path.md)
is optional and limited to its declared topology and spec. Other reactions can
use directly prepared Gaussian inputs without adopting that path format.

Start from a validated saddle candidate and preserve path direction. Check the
IRC origin against that structure, termination and path completeness in both
directions, final geometry and gradient, and whether endpoint optimization is
needed before basin assignment. Compare each endpoint with an explicit target
Artifact using mapping, key internal coordinates, stereochemistry, and a
deterministic structure comparison.

Record direction-specific path and endpoint facts separately. Missing or
contradictory endpoint evidence is a research note, but does not implicitly
change research Node or hypothesis status. Read
[irc_validation.md](references/irc_validation.md).
