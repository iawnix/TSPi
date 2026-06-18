# Mechanism Preflight And Reflection

Use this before spending compute time and after every failed or ambiguous branch.

## Mechanism Preflight

Record:

- total charge and multiplicity;
- reactant and product atom mapping;
- optimized reactant/product structures and level of theory;
- expected forming and breaking bonds;
- key distances and angles at the reaction center;
- whether the reaction is closed-shell, open-shell, ionic, radical, proton transfer, HAT, PCET, rearrangement, spin crossover, atom transfer, substitution, or dissociation;
- likely electronic diagnostics: `<S^2>`, spin density, charge distribution, bond-order proxy, orbital occupation, equivalent atom mappings.

## Mechanism Classes

## Mechanism Analysis Plan And Evidence Layers

Do not stop at a geometry-only explanation when the chemistry is ambiguous,
open-shell, electronically delicate, or being promoted to `accepted_ts`. Record
the planned diagnostics first in `mechanism_model.json` under `analysis_plan`.
After outputs exist, record evidence-backed layers through
the node closure and mechanism-analysis records. Read
`references/mechanism_analysis_sources.md` before deciding which method can
support each layer:

- reaction type: the proposed elementary class and why competing classes are
  less consistent with the evidence;
- reaction center: mapped atoms, forming/breaking bonds, angle changes,
  fragment identities, and imaginary-mode participation;
- electronic: charge/multiplicity consistency, `<S^2>`, spin-density movement,
  donor/acceptor charge migration, and state mixing risk;
- orbital: frontier orbital or population descriptors when available, or an
  explicit `unavailable` record when the calculation output lacks the needed
  sections;
- energy: endpoint energies, TS energy, reaction energy, barrier estimate, and
  whether the energy profile supports the proposed elementary step.

Each layer must be provenance-backed: cite closure evidence records or put the
direct output/parsed descriptor in the `source` field of the mechanism-analysis
record.

Use `unavailable` instead of inventing electronic, orbital, or population
diagnostics from route text, filenames, or neighboring calculations.

### Proton Transfer

A true proton-transfer TS should have an imaginary mode that primarily moves H along the donor-acceptor coordinate, and the two sides should optimize/connect to different protonation sites. If both endpoint molecules already vibrate along that H direction without crossing to another minimum, do not call it a PT TS from the frequency alone.

### HAT or PCET

For open-shell H motion, distinguish proton transfer from H atom transfer or PCET. Check `<S^2>`, spin density migration, charge changes on donor/acceptor, and whether the product is a radical or ionic resonance form.

### Rearrangement or Bond-Order Shift

For intramolecular oxygen-site or resonance-equivalent rearrangements, the "product" may not be a distinct minimum. Compare bond-order proxies, equivalent atom mappings, and optimized endpoint stability before forcing an IRC assignment.

### dMECP-Suitable Atom Transfer

QBICS dMECP is strongest for AB+C=A+BC-like bond-switching where reactant and product diabatic fragment states are chemically natural. For intramolecular proton or oxygen-site rearrangements, dMECP fragment definitions are hypotheses, not proof.

## Failure Classification Rules

Do not expose program-specific failure labels as public node states. The public
state is `node_disposition` plus `phase`; exact Gaussian, xTB, QBICS, parser,
or chemistry diagnostic labels belong in `closure_explanation.program.facts`.
Backtracking reasons belong in the next node rationale and mechanism
implication after reading `report_workspace`.

Use this mapping when closing failed or ambiguous branches:

| Situation | `claim_status` | `outcome` | Example `outcome_code` |
| --- | --- | --- | --- |
| Wrong host, missing executable, bad route, shell quoting failure, or setup crash before reliable chemistry evidence | `not_evaluated` | `numerical_failure` | `input_or_environment_error`, `gaussian_redcar_gtrans_failure`, `qst2_internal_coordinate_failure` |
| SCF fails before reliable geometry evidence | `not_evaluated` | `numerical_failure` | `scf_nonconvergence` |
| Parser cannot safely extract the required evidence | `not_evaluated` or `ambiguous` | `parser_refused` | `missing_orientation_block`, `incomplete_gaussian_output` |
| Path search used unoptimized or non-distinct endpoint references | `rejected` or `ambiguous` | `wrong_endpoint` | `endpoint_not_optimized`, `not_distinct_endpoints`, `ambiguous_pose` |
| Candidate collapses to one endpoint | `rejected` | `wrong_endpoint` | `candidate_collapsed_to_reactant`, `candidate_collapsed_to_product` |
| One imaginary mode is unrelated to the intended reaction-center motion | `rejected` or `ambiguous` | `wrong_mode` | `wrong_reaction_coordinate`, `soft_conformational_saddle` |
| TS/Freq job fails before a reliable stationary-point claim | `not_evaluated` | `numerical_failure` or `parser_refused` | `frequency_validation_failed` |
| TS/Freq job reaches a stationary point but the mode/frequency pattern is not the intended TS | `rejected` or `ambiguous` | `wrong_mode` | `frequency_validation_failed`, `wrong_reaction_coordinate` |
| IRC or optimized displacement endpoints do not match intended references | `rejected` or `ambiguous` | `wrong_endpoint` | `irc_not_connected`, `endpoint_assignment_failed` |
| Spin contamination, state mixing, or mechanism mismatch refutes the branch | `rejected` | `chemical_failure` | `spin_contamination_or_state_mixing`, `mechanism_hypothesis_mismatch` |
| Reference-surface mismatch changes endpoint identity | `rejected` or `ambiguous` | `wrong_endpoint` | `reference_surface_mismatch` |

## Reflection Questions

Answer these in failed/ambiguous branches:

- Did the calculation fail numerically, or did it disprove a mechanism assumption?
- Was the endpoint reference a real minimum at the chosen level?
- Is the imaginary mode reaction-center motion or a soft/conformational mode?
- Are spin, charge, and multiplicity chemically consistent across both sides?
- Did the candidate collapse to reactant/product, and what does that say about barrier shape?
- Is the intended product a distinct minimum, a resonance/equivalent atom relabeling, or a different electronic state?
- Which ancestor should be branched from next, and what changed chemical hypothesis will be tested?
