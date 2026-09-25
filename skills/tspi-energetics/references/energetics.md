# Thermochemistry, elementary kinetics and networks

`thermochemistry.evaluate` takes an `electronic` Gaussian log and optional
`thermal` log. Specify `species_key`, `quantity` (`E`, `E_ZPE`, `H`, `G`),
`electronic_state`, `stationary_kind`, `methods`, and conditions. Method strings
identify exact method/basis tokens from the route, e.g. `B3LYP/6-31G(d)`.
Separate sources require `methods.composite=true` and atom-ordered geometry
agreement within an explicit tolerance. Distinct methods are recorded, not
silently blended. XYZ/Gaussian geometry does not encode isotope masses here;
isotope-specific RRHO and KIE are outside version 1.
Electronic-energy extraction currently supports matched HF/Kohn-Sham SCF
totals. A correlated method's reference SCF energy must not be reported as its
MP2/CCSD(T) energy; those outputs require a dedicated energy parser.

Conditions include temperature in kelvin, phase, solution solvent when relevant,
`source_standard_state` and target `standard_state`. Each standard state has
`kind`, `value`, and `unit`: pressure (`bar`, `atm`, `Pa`) or concentration
(`mol/L`). G conversion is `RT ln(c_target/c_source)` per species. It is not
applied to E, E+ZPE or H. Actual reactant concentrations are a separate rate input.

The default model uses parsed Gaussian corrections at the logged temperature
and pressure. `model.kind=rrho` uses ASE ideal-gas thermochemistry with explicit
`geometry` (`monatomic`, `linear`, `nonlinear`), rotational `symmetry_number`,
and optional `frequency_scale`. Exactly one unstable mode is excluded for a TS;
minima require none. Low-frequency anharmonicity, hindered rotors, ensembles,
quasi-harmonic models and uncertainty propagation are not inferred.

`barrier.evaluate` requires reactant, product and TS thermal artifacts. Explicit
stoichiometric coefficients default to one per supplied artifact. Quantity,
conditions, method and scaling conventions must agree. Composition/charge and
possible spin coupling are checked. Spin compatibility is not evidence of
adiabatic surface continuity. Electronic barriers never substitute for Gibbs
barriers in kinetics.

`kinetics.tst` uses concentration-form elementary TST:

`k_m = κ k_B T/h · (c°)^(1−m) · exp(−ΔG‡/RT)`.

For first order the unit is `s^-1`; for second order it is `L mol^-1 s^-1`.
Optional `concentrations_molar` produce a separate rate in `mol/L/s`. Supply κ
explicitly when departing from its default of 1. No tunnelling/recrossing or
diffusion correction is inferred. Negative barriers are flagged as outside a
simple activated-TST interpretation; extreme constants remain available as ln k.

`kinetics.branching` computes normalized initial rate weights only for the same
equilibrated precursor with irreversible products and no product interconversion.
It requires those assumptions explicitly. Cycles, depletion and time-dependent
yields need a kinetics model beyond this capability.

`mechanism.step.define` records a balanced ReactionSpec, reversibility and
optional structural audit/barrier/rate evidence. Missing evidence remains visible.
`mechanism.network.assemble` combines selected StepRecords as stoichiometric
hyperedges, allowing parallel steps, intermediates, reversibility and cycles.
Resolve key collisions with explicit `species_aliases` keyed `step/local_species`.
`mechanism.network.audit` checks balance, identity conflicts and missing evidence.
Optional bounded path enumeration is qualitative availability; it does not
model depletion or rank kinetically preferred pathways.

`mechanism.energy_profile` requires a selected path and `initial_composition`.
It preserves stoichiometric participants and spectator pools while accumulating
ΔG and local barrier heights on one reference. Its generated `energy_profile.json`
uses the existing `ts-curve-data/1` contract and can be passed to `artifact.render curve`.
The profile is a selected comparison, not a claim of complete mechanism discovery.
Reports and Node Web details link analyses back to source files and Findings.
