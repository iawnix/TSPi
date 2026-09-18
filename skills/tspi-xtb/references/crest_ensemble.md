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

## Runtime Readiness

The remote `crest` software profile must select an operator-managed, versioned
CREST binary. Its activation script must make the compatible xTB executable
available without changing the research workspace. Run `TSPi --check-remote`
after deployment or profile changes and before the first calculation. A missing
command or activation script is an operational failure, not a scientific
result.

Do not install or upgrade CREST from a calculation job. Follow the
[cluster deployment procedure](../../../docs/INSTALLATION.md#deploy-crest),
then use a bounded compute-node smoke search. A zero scheduler exit status with
any required primary artifact missing is a program or integration failure, not
an empty conformer ensemble.

Use relative energy to rank conformers within the declared CREST calculation.
Evaluate free energies and barriers with their required corrections. Preserve the
ensemble and selection rationale as artifacts and Findings so another
method can reproduce or challenge the choice.
