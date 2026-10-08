# Transition-State Validation

Transition-state validation separates program completion, stationary-point
evidence, mode assignment, structure identity, and scientific interpretation.
No single parser flag establishes all of them.

The [Gaussian runner](../../gaussian/SKILL.md) writes `parsed.json` using
`gaussian_io.py::parse_log`. The parser extracts termination, convergence,
stationary markers, frequencies, geometry and Cartesian normal-mode vectors
from the final harmonic table. Its `section_index` argument is zero based. Select the relevant section
and compare the output route, charge, multiplicity, method and basis with the input.

For a classical first-order saddle, require optimization convergence and one
imaginary mode that represents the proposed elementary step. Numerical noise,
constraints, flat modes, and competing imaginary modes must remain visible.
Inspect the displacement vectors rather than relying on frequency count alone.

For the declared DA path, `chemical.gaussian_saddle` checks the raw collected log
against a registered path spec, including method/resources, convergence, complete
frequencies and simultaneous forming-bond motion. See the [executable path](../../candidate-generation/references/gaussian_path.md).
Its normalized displacement threshold is a limited mode check, not proof of an entire mechanism.
The older `chemical.gaussian_frequency` checks only normal termination and one negative frequency.

Validate element count, atom mapping, charge, multiplicity, electronic state,
key distances and dihedrals, stereochemistry, and the absence of unintended
fragment or conformer changes. Treat SCF instability, spin contamination,
state ambiguity, method sensitivity, and missing robustness checks as separate
issues.

Record each verified property as a FactFinding with the primary output and
analysis Artifact references. Record missing, conflicting, or ambiguous
evidence as an IssueFinding. These records inform later status decisions but do
not change a Node or Claim automatically. IRC connectivity is a separate
validation dimension handled by `irc`.
