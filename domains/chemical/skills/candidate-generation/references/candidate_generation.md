# Candidate Generation

Candidate generation creates structures for transition-state optimization and
characterization.

## Root Choice

Choose among chemically informed construction, constrained scans, QST2/QST3,
direct TS optimization, NEB/path interpolation, conformer search, fragment
approach sampling, or another justified method. Select their order from the
current hypothesis and evidence.

Before QST2/QST3, verify atom count/order or an explicit map, charge/spin,
endpoint preparation/optimization status, conformational compatibility, and that both
structures describe one elementary step. Record why this interpolation tests
the proposed step.

## Recording

Continue the existing Node for this question, or create an independent branch with research_create. Put the question in goal and the candidate hypothesis in proposal.
Bind all seeds through logical artifact IDs. Link every immutable compute intent
and preserve method/parameters. After collection, record candidate coordinates,
energies, constraints, and provenance as separate research notes when useful.

Use research notes for distorted geometry, atom-map ambiguity, fragment collapse,
unexpected bonding, electronic-state concern, or missing conformers.

## Follow-Up

A candidate still requires scientifically appropriate optimization and
characterization. For a classical TS this normally separates:

- stationary-point/convergence research notes;
- imaginary-mode/reaction-coordinate assignment research notes;
- bidirectional connectivity and endpoint identity research notes;
- additional state, robustness, stereochemical, or thermochemical checks.

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.
