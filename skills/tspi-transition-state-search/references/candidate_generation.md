# Candidate Generation

Candidate generation creates structures for transition-state optimization and
characterization.

## Root Choice

Choose among chemically informed construction, constrained scans, QST2/QST3,
direct TS optimization, NEB/path interpolation, conformer search, fragment
approach sampling, or another justified method. Select their order from the
current hypothesis and evidence.

Before QST2/QST3, verify atom count/order or an explicit map, charge/spin,
optimized compatible endpoints, conformational compatibility, and that both
structures describe one elementary step. Record why this interpolation tests
the proposed step.

## Recording

Create a ResearchNode whose objective states what hypothesis the candidate tests.
Bind all seeds through logical artifact IDs. Link every immutable compute intent
and preserve method/parameters. After collection, record candidate coordinates,
energies, constraints, and provenance as separate Findings when useful.

Use Findings for distorted geometry, atom-map ambiguity, fragment collapse,
unexpected bonding, electronic-state concern, or missing conformers.

## Follow-Up

A candidate still requires scientifically appropriate optimization and
characterization. For a classical TS this normally separates:

- stationary-point/convergence FactFindings;
- imaginary-mode/reaction-coordinate assignment Findings;
- bidirectional connectivity and endpoint identity Findings;
- additional state, robustness, stereochemical, or thermochemical checks.

Create a Gate only when a completion or comparison criterion needs a visible
verdict. Record alternative candidates or methods as branches and compare
their Findings when choosing the next step.
