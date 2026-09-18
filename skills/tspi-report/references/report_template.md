# Report Contract

Build the report from the current `ResearchMap` and registered logical
Artifacts with `ts_report`. The report is a package of the map revision and
the selected operational records; it is not a new state model.

## Required Content

Include:

1. map identity, revision, focus Claims/Nodes, and conclusion boundary;
2. Phases with their grouped Nodes;
3. Claims and Claim relations, including alternatives and conflicts;
4. Node objectives, dependencies, states, outcomes, and open questions;
5. calculation intents and primary Artifact references;
6. FactFindings with values, units, provenance, and source references;
7. IssueFindings, including open limitations and unresolved conflicts;
8. Gates with criteria and their evaluations;
9. operational follow-up such as pending runs, failed attempts, Review advice,
   and notification status;
10. missing corrections, uncertainty, and next research questions.

## Numerical Discipline

Keep electronic energy, E+ZPE, enthalpy, and free energy distinct. Report units,
reference state, temperature, pressure, standard-state correction, frequency
scaling, conformer treatment, solvation, dispersion, and missing corrections.
Mark unavailable values as missing. Every numerical or structural statement
cites a FactFinding and its source Artifact; an IssueFinding carries the
limitation when the evidence is incomplete.

## Package Integrity

Each export creates a new package directory. Its manifest binds the source map
revision, operational records, file paths, sizes, and SHA-256 digests. A
package is usable only when the manifest matches the actual regular files. Do
not edit a generated report and present it as a newer ResearchMap revision.
