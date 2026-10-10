# Transition-State Validation

Transition-state validation separates program completion, stationary-point
evidence, mode assignment, structure identity, and scientific interpretation.
No single parser flag establishes all of them.

The [Gaussian runner](../../gaussian/SKILL.md) writes `parsed.json` using
`gaussian_io.py::parse_log`. The parser extracts termination, convergence,
stationary markers, frequencies, geometry and Cartesian normal-mode vectors
from the final harmonic table. Its `section_index` argument is zero based. Select the relevant section
and compare the output route, charge, multiplicity, method and basis with the input.
Later incomplete optimization or harmonic sections do not inherit earlier passing
evidence. Convergence requires all four rows from the final optimization table.

For a classical first-order saddle, require optimization convergence and one
imaginary mode that represents the proposed elementary step. Numerical noise,
constraints, flat modes, and competing imaginary modes must remain visible.
Inspect the displacement vectors rather than relying on frequency count alone.

Define relevant displacement from the current hypothesis: bond formation, bond
cleavage, proton transfer, rearrangement, or another reaction coordinate. Do not
prescribe two forming bonds or one concerted motion pattern for every reaction.
Compare geometries displaced in both signs of the mode and changes in relevant
internal coordinates; the overall sign of an eigenvector has no physical meaning.

Check a helper's scope before selecting it. `chemical.gaussian_frequency@1`
checks normal termination without an error marker and one negative frequency in
a finite numeric table, and cannot certify a
transition state. The [specialized path validators](../../candidate-generation/references/gaussian_path.md)
have additional topology and input constraints and apply only to the systems
specified there. For other systems, use primary outputs and analysis scripts
suited to the actual reaction; no specialized acceptance profile is required.

Validate element count, atom mapping, charge, multiplicity, electronic state,
key distances and dihedrals, stereochemistry, and the absence of unintended
fragment or conformer changes. Treat SCF instability, spin contamination,
state ambiguity, method sensitivity, and missing robustness checks as separate
issues.

Record each verified property as a research note with the primary output and
analysis Artifact references. Record missing, conflicting, or ambiguous
evidence as a research note. These records inform later status decisions but do
not change a research Node or hypothesis automatically. IRC connectivity is a separate
validation dimension handled by `irc`.
