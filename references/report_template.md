# Transition-State Report Template Contract

This skill reports transition-state searches as evidence-layered scientific
claims, not as a generic calculation log. The final report must separate:

- candidate generation;
- TS/Freq validation;
- connectivity or IRC validation;
- accepted-TS audit;
- pathway audit.

The report must state the highest validated layer reached. It must not call a
candidate, scan point, NEB image, dMECP structure, or isolated imaginary
frequency an accepted transition state. `ts_report` should be able to write a
report package with `final_report.md`, `report_context.json`, `assets/`, and
`email_summary.md`; missing render or energy data must be reported as missing
evidence rather than silently omitted.

## External Reporting Guidance Used

- ACS computational-data guidance asks computational studies to provide enough
  detail for reproducibility, including method keywords, package versions,
  machine-readable coordinates for key stationary points, absolute energies,
  relevant vibrational frequencies, and enough information for software access
  or reproduction.
  Source: https://researcher-resources.acs.org/publish/data_guidelines
- ACS journal author guidance for computational data asks reports to identify
  the level of theory, basis set, input parameters, program, optimized
  coordinates, total energies, number of imaginary frequencies where relevant,
  nonstandard constraints, convergence criteria, and spin treatment.
  Source: https://researcher-resources.acs.org/publish/author_guidelines?coden=orlef7
- ACS research data guidance also emphasizes transparent and rigorous reporting
  so trained readers can reproduce and evaluate the work.
  Source: https://researcher-resources.acs.org/publish/data_guidelines
- IUPAC guidance for computational results asks authors to report constraints,
  nondefault optimization convergence limits, force-constant units and
  coordinates, whether a transition structure has exactly one imaginary
  frequency, and whether calculations identified the linked minima.
  Source: https://media.iupac.org/publications/pac/2000/pdf/7208x1449.pdf
- WebMO's computational chemistry help summarizes the practical TS check:
  frequency calculation with one imaginary mode plus forward and reverse IRC
  paths leading to reactant and product basins.
  Source: https://www.webmo.net/link/help/CalculationTypes.html
- SCM AMS IRC documentation describes IRC as a path from a TS down to local
  minima in mass-weighted coordinates, with forward and backward directions and
  method settings that should be reported.
  Source: https://www.scm.com/doc/AMS/Tasks/IRC.html
- Recent TS-mode analysis work motivates reporting chemically meaningful
  internal-coordinate changes for imaginary modes and reaction-coordinate
  trajectories rather than only Cartesian displacement pictures.
  Source: https://eprints.whiterose.ac.uk/id/eprint/238213/

## Required Report Sections

Use `templates/ts_final_report.md` as the fillable template. A completed report
should include:

1. Executive verdict and highest validated evidence layer.
2. Reaction overview: system, endpoint, atom-mapping, charge, multiplicity,
   reaction center, transferred atoms, and pathway scope.
3. R-TS-P structural panel with reactant, accepted/selected TS, product, and
   reaction-center key distances.
4. Imaginary mode / vibration analysis, including mode+ and mode- displacement
   geometry or distance changes.
5. IRC / connectivity evidence including settings, endpoint assignments,
   endpoint optimization state, RMSD/key-bond metrics, and diagnostics.
6. Energy profile across R, TS, and P with electronic, E+ZPE, and when
   available thermal free-energy relative values. Report clear missing-data
   notes when stationary-point energies or corrections are incomplete or not
   comparable.
7. Mechanistic interpretation explaining how the reaction occurs, including
   synchrony/asynchrony, TS resemblance, alternative hypotheses, and electronic
   structure boundaries.
8. Evidence audit preserving the candidate generation, TS/Freq validation,
   connectivity validation, accepted-TS audit, and pathway audit layers.
9. Search tree summary with node decisions and evidence references.
10. Limitations and follow-up.
11. Artifact and evidence appendix.

The evidence audit should retain:

- Candidate-generation evidence and rejected-branch rationale.
- TS/Freq evidence including convergence, one-imaginary-frequency status,
   imaginary-mode assignment, key internal-coordinate changes, and artifacts.
- Connectivity or IRC evidence including settings, endpoint assignments,
  endpoint optimization state, RMSD/key-bond metrics, and diagnostics.
- Accepted-TS audit only when TS/Freq and connectivity gates both support the
   same hypothesis.
- Pathway audit, including negative-audit conclusions such as
   `pathway_not_accepted`.

## Minimum Acceptance Gates

Accepted TS language is allowed only when all are present:

- `tsfreq_gate` evidence for the same `hypothesis_id`;
- `connectivity_gate` evidence for the same `hypothesis_id`;
- `stereochemical_connectivity_gate` for the same `hypothesis_id` when the
  hypothesis declares stereochemical requirements;
- `endpoint_identity_gate`, `intermediate_identity_gate`,
  `electronic_structure_gate`, `state_character_gate`, and/or
  `shared_basin_consistency_gate` for the same `hypothesis_id` when the
  hypothesis declares the corresponding mechanism claims;
- an `accepted_audit` node or accepted artifact written by `ts_workspace`;
- no unresolved contradiction in pathway audit evidence for the reported
  pathway step.

Report geometry connectivity, endpoint stability, electronic/state identity,
shared-basin consistency, and final R to P pathway proof as separate evidence
layers. Do not let IRC endpoint assignment stand in for an electronic-identity
claim.

If a pathway audit is negative, report the branch as failed or not accepted and
state the next branch or open question separately.

## Report Style

- Conclusion first, then evidence.
- Use tables for node history, key structures, energy profile, and artifact
  provenance.
- Keep numeric values tied to units and artifact paths.
- Distinguish program status from scientific claim verdict.
- Cite evidence IDs rather than relying on prose memory.
- Put long coordinate blocks or full log excerpts in appendices or file links.
