# CREST Ensemble Contract

Use the installed CREST command through generic Job Runtime; there is no bundled
CREST workflow adapter. Read the installed version's actual options. Preserve the
XYZ input, charge, unpaired electrons, xTB method, search and optimization levels,
threads and solvent settings as applicable. Validate them against that program's contract.

The required primary set is `crest.out`, `crest_best.xyz`,
`crest_conformers.xyz`, and `crest.energies`. A completed search requires a
normal termination marker, all required files, a parsed ensemble, and matching
conformer and energy-table counts. Verify atom count and coordinate identity
before using an ensemble member in a later research Node.

## Runtime Readiness

The remote environment's `crest` Backend binding must select an operator-managed, versioned
CREST binary. Its activation script must make the compatible xTB executable
available without changing the research workspace. Check the declared target with `"$RESEARCH_AGENT_PYTHON" -m research_agent.application.environment_check --config "$RESEARCH_AGENT_JOB_CONFIG"` after installation changes, then run a bounded scientific Job. A missing
command or activation script is an operational failure, not a scientific
result.

Do not install or upgrade CREST from a calculation job. Follow the
[execution target configuration](../../../../../docs/INSTALLATION.md#configure-execution-targets),
then use a bounded compute-node smoke search. A zero scheduler exit status with
any required primary artifact missing is a program or integration failure, not
an empty conformer ensemble.

Use relative energy to rank conformers within the declared CREST calculation.
Evaluate free energies and barriers with their required corrections. Preserve the
ensemble and selection rationale as artifacts and research notes so another
method can reproduce or challenge the choice.
