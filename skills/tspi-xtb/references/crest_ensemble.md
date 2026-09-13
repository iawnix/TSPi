# CREST Ensemble Contract

The registered capability is `crest.conformer_search`. It accepts one `xyz`
input and explicit charge, unpaired electrons, xTB method, search level,
optimization level, thread, and solvent settings. Solvent and solvent model
must be supplied together.

The required primary set is `crest.out`, `crest_best.xyz`,
`crest_conformers.xyz`, and `crest.energies`. A completed search requires a
normal termination marker, all required files, a parsed ensemble, and matching
conformer and energy-table counts. Verify atom count and coordinate identity
before using an ensemble member in a later Node.

Use relative energy to rank conformers within the declared CREST calculation.
Evaluate free energies and barriers with their required corrections. Preserve the
ensemble and selection rationale as artifacts and Observations so another
method can reproduce or challenge the choice.
