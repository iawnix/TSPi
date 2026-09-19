# Transition-State Validation

Transition-state validation separates program completion, stationary-point
evidence, mode assignment, structure identity, and scientific interpretation.
No single parser flag establishes all of them.

`gaussian.output.analyze` reads a selected Gaussian job section
(`section_index` is zero based). It extracts termination, convergence,
stationary markers, frequencies, geometry, and normal-mode vectors. Select the
section that corresponds to the declared task and compare the output route,
charge, multiplicity, method, and basis with the immutable calculation intent.

For a classical first-order saddle, require optimization convergence and one
imaginary mode that represents the proposed elementary step. Numerical noise,
constraints, flat modes, and competing imaginary modes must remain visible.
Inspect the displacement vectors rather than relying on frequency count alone.

`vibration.analyze_mode` accepts zero-based `mode_index` and explicit atom-pair
and sign expectations in `bonds`. It reports bond-length derivatives and
absolute cosine overlap; the overall normal-mode sign is arbitrary. Use enough
chemically relevant coordinates to distinguish competing collective motions.
The reported overlap is not a mass-weighted full reaction-coordinate metric.

Validate element count, atom mapping, charge, multiplicity, electronic state,
key distances and dihedrals, stereochemistry, and the absence of unintended
fragment or conformer changes. Treat SCF instability, spin contamination,
state ambiguity, method sensitivity, and missing robustness checks as separate
issues.

Record each verified property as a FactFinding with the primary output and
analysis Artifact references. Record missing, conflicting, or ambiguous
evidence as an IssueFinding. These records inform later status decisions but do
not change a Node or Claim automatically. IRC connectivity is a separate
validation dimension handled by `tspi-irc`.
