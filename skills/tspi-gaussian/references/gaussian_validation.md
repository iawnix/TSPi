# Gaussian Validation

Verify the collected primary Gaussian output before recording scientific
Observations.

## Program And Intent

Check normal termination, route section, method/basis, charge, multiplicity,
solvation/environment, dispersion, grid, SCF treatment, optimization keywords,
frequency parameters, constraints, resources, and material warnings against the
immutable intent. Use Gaussian's canonical keyword spelling, for example
`M062X`, and reject malformed route syntax before remote submission when the
adapter can determine it.

## Classical Stationary Point

Record separate semantic Observations for normal termination, stationary-point
confirmation, optimization convergence, imaginary-frequency count, and method
agreement. The built-in `classical-ts@1` template evaluates these exact concepts.

Exactly one imaginary frequency is necessary for an ordinary first-order
saddle. Establish its relation to the claimed step by recording the frequency and
mode vector/visualization separately. Use `reaction-coordinate@1` only after
the displacement matches the declared bond changes or other coordinate.

`reaction-coordinate@1` takes `subject_ref` as its parameter. Keep the concrete bond-change assignment in
the immutable Observation value/qualifiers, and record
`vibration.mode_matches_reaction_coordinate=true` only after checking that
assignment. `classical-ts@1` gates the imaginary-frequency count, while the
numeric frequency remains separate evidence unless an explicit ProofSpec checks
it. Query the focused validation capability instead of guessing concept aliases.

## Electronic And Numerical Limits

Record SCF instability, spin contamination, wavefunction stability, state
identity, near-degeneracy, integration warnings, and method sensitivity as
Observations or Findings. Add electronic-structure, state-character, or
method-robustness ProofSpecs when relevant.

Keep E, E+ZPE, H, and G separate with temperature, pressure, standard state,
scaling, and missing corrections. Use these conditions when assessing
thermochemical and mechanistic Claims.
