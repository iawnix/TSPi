# Report Contract

Build the standard report from a valid workspace with `ts_report`. The
authoritative renderer is `python/ts_agent/report/builder.py`; there is no fill-in Markdown
template with a second, drifting report contract. Add any extra narrative as a
separate report-package asset.

## Required Projection

The report package must expose, across `final_report.md` and its bound context
files:

1. workspace identity, scientific revision, focus Claims/Nodes, and explicit
   conclusion boundary;
2. ResearchPhases and their grouped Nodes as the human roadmap;
3. Claims and Claim relations, including alternatives and conflicts;
4. ResearchNode DAG dependencies, objectives, Claim scope, outcomes, and open
   questions;
5. computational protocols and primary artifact refs;
6. semantic Observations with values, units, qualifiers, provenance, and
   digests;
7. frozen ProofSpecs and deterministic ValidationResults;
8. Findings, including resolved and open blocking items;
9. immutable acceptance history, profile versions, and explicit current/stale
   status;
10. deterministic activities, activity integrity, unresolved compute controls,
   pending Review dispositions, and notification state as operational follow-up;
11. limitations, missing corrections, and open scientific questions.

## Acceptance Language

Do not describe a candidate as accepted from normal termination, convergence,
one imaginary frequency, a Review opinion, or a Claim status. Cite the actual
current acceptance record and its profile, ProofSpecs, passing ValidationResults,
and Finding snapshot. A historical record whose inputs have
changed must be labeled stale, not used as a current accepted verdict.

For a classical TS, keep stationary-point, reaction-coordinate, and
connectivity dimensions separate. Add identity, electronic structure,
state-character, robustness, thermochemistry, or pathway validation when the
Claim and scientific system require them.

## Numerical Discipline

Keep electronic energy, E+ZPE, enthalpy, and free energy distinct. Report units,
reference state, temperature, pressure, standard-state correction, frequency
scaling, conformer treatment, solvation/environment, dispersion, and missing
corrections. Do not infer a missing value.

Every numerical or structural statement cites a registered Observation and its
source artifact. Review journals, activity records, scheduler state, and
notification receipts remain operational provenance.

## Package Integrity

The report builder creates a new no-overwrite directory atomically. Its
manifest binds `workspace_revision`, `operational_revision`, every file path,
size, and SHA-256. `activities.json` records the deterministic activity
projection. A package is usable only when its manifest matches the actual
regular files.
