# Thermochemistry, elementary kinetics and networks

This reference defines scientific checks, not a catalog of callable analysis
capabilities. The package has no bundled thermochemistry, barrier, TST, branching
or reaction-network executor. Run a concrete analysis script through Job Runtime
and register its inputs and outputs. `artifact_derive` only records a descriptor.
The [Gaussian runner](../../gaussian/SKILL.md) parses electronic energy and available
thermal corrections; inspect the actual output fields and missing values.

Keep species identity, quantity (`E`, `E+ZPE`, `H`, `G`), units, method/basis,
electronic state, stationary-point assignment and conditions explicit. Separate
electronic and thermal sources require compatible structures and atom order plus
a declared composite treatment. A correlated method's reference SCF energy must
not be reported as its MP2/CCSD(T) energy; use a dedicated parser for that quantity.

Conditions include temperature, phase, solvent, source and target standard states.
Converting a gas pressure to concentration requires `c_source = p_source / RT`
in compatible units; the per-species Gibbs correction is `RT ln(c_target/c_source)`.
Do not apply this correction to E, E+ZPE or H. Actual concentrations are separate rate inputs.
Use the logged thermal model unless a different model is explicitly implemented.
RRHO treatment must specify geometry class, rotational symmetry and frequency scaling;
minima have no unstable mode and a first-order TS excludes its one unstable mode.
Low-frequency corrections, conformer ensembles and isotope effects need their own evidence.

Compute reaction energies and barriers with explicit stoichiometry and matching
quantities, conditions and method conventions. Check composition, charge and spin;
spin compatibility does not prove adiabatic continuity. Electronic barriers are not Gibbs barriers.

Concentration-form elementary TST is
`k_m = κ k_B T/h · (c°)^(1−m) · exp(−ΔG‡/RT)`.
First-order units are `s^-1`; second-order units are `L mol^-1 s^-1`.
State κ and any tunnelling, recrossing or diffusion treatment explicitly. Negative
barriers require scrutiny of the activated-TST assumptions. Initial branching weights
require a shared equilibrated precursor, irreversible products and no interconversion;
cycles, depletion and time-dependent yields need an explicit kinetic model.

For a mechanism network, preserve species identities, balanced stoichiometry,
reversibility, competing paths and missing evidence. An energy profile must select
a path and common reference, accounting for all stoichiometric participants and
spectators. A profile neither proves complete mechanism discovery nor identifies
kinetically preferred paths by itself. Link report values to the executed analysis and source Artifacts.
