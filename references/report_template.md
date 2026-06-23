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
frequency an accepted transition state.

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
2. System, endpoint, atom-mapping, charge, multiplicity, and pathway scope.
3. Computational protocol sufficient to reproduce the calculation.
4. Search tree summary with node decisions and evidence references.
5. Candidate-generation evidence and rejected-branch rationale.
6. TS/Freq evidence including convergence, one-imaginary-frequency status,
   imaginary-mode assignment, key internal-coordinate changes, and artifacts.
7. Connectivity or IRC evidence including settings, endpoint assignments,
   endpoint optimization state, RMSD/key-bond metrics, and diagnostics.
8. Accepted-TS audit only when TS/Freq and connectivity gates both support the
   same hypothesis.
9. Pathway audit, including negative-audit conclusions such as
   `pathway_not_accepted`.
10. Energy profile, coordinates, artifacts, hashes, logs, and open questions.

## Minimum Acceptance Gates

Accepted TS language is allowed only when all are present:

- `tsfreq_gate` evidence for the same `hypothesis_id`;
- `connectivity_gate` evidence for the same `hypothesis_id`;
- an `accepted_audit` node or accepted artifact written by `ts_workspace`;
- no unresolved contradiction in pathway audit evidence for the reported
  pathway step.

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
