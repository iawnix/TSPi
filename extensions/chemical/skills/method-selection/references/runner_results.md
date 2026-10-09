# Scientific runner results

CF22D, xTB, and Gaussian produce `science-result/2`. `checks_passed` says that
the runner completed its requested numeric and output checks. It does not
certify a minimum, saddle, mechanism, or fulfilled user requirement.
`scientific_validation` remains `not_assessed`; validators and Research State
store scientific assessments separately. Job receipts own execution and collection
status. Preserve failed results and raw logs without rewriting their verdicts.

Coordinates are angstrom and electronic energies are hartree. Other quantities
carry units in their field names. Public runner arguments use integer charge
and `--multiplicity` (2S+1, default 1). The runner checks XYZ electron-count parity
and converts multiplicity to PySCF spin or xTB unpaired electrons internally.
Broken-symmetry and other states not determined by this convention need an
explicitly supported method/input; do not infer them from a multiplicity alone.

`opt-sp` uses the optimized geometry for its single point. Check that the SP
input digest equals the optimization geometry digest, and that both steps
completed. Independent SP and optimization calls need an explicit Artifact dependency.

The preparation command stages pinned scripts and the executor's required outputs.
The Agent supplies scientific inputs and parameters, then submits the returned
request file/digest through `job_start`. An unavailable environment is a pending
capability, not permission to silently substitute a method. See
[runtime environments](runtime_environment.md) for target selection.

Reports summarize source files and preserve their digests. Historical
`science-result/1` files used `validated` inconsistently, so the report leaves
their check status unknown. It never treats a runner flag as scientific acceptance.
