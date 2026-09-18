# Gaussian Validation

Verify the collected primary Gaussian output before adding map Findings.

## Program And Intent

Check normal termination, route, method/basis, charge, multiplicity,
solvation/environment, dispersion, grid, SCF treatment, optimization and
frequency keywords, constraints, resources, and material warnings against the
immutable calculation intent. Reject malformed input before remote submission
when the adapter can determine it.

## Stationary Point

Keep normal termination, stationary-point confirmation, optimization
convergence, imaginary-frequency count, and method agreement as separate
FactFindings. For an ordinary first-order saddle, exactly one imaginary
frequency is necessary. Record the frequency, displacement, and visualization
as distinct source-backed values; relate the displacement to the claimed bond
changes before treating it as a reaction-coordinate fact.

## Limits And Conditions

Record SCF instability, spin contamination, wavefunction instability,
electronic-state ambiguity, near-degeneracy, integration warnings, and method
sensitivity as IssueFindings when they affect interpretation. Keep E, E+ZPE,
H, and G separate with temperature, pressure, standard state, scaling, and
missing corrections. Use a NodeGate or ClaimGate only when a visible criterion
and evaluation help close or assess the research question.
