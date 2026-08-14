# Candidate Generation

Candidate generation proposes geometries for later scientific testing. It does
not establish transition-state acceptance.

## Root Choice

Choose methods from the reaction class, mapping, conformational uncertainty,
known endpoints, dimensionality, spin/electronic concerns, cost, and available
software. The adapter capability catalog describes expressible operations only;
live readiness requires separate environment or remote diagnostics.

Gaussian is a first-class candidate-generation backend for relaxed scans,
QST2/QST3, and direct TS optimization when chemically justified. xTB scans,
CREST conformers, ASE NEB images, and other supported methods may be equally
appropriate. Do not impose a universal low-cost-first or Gaussian-first order.

Do not default to QST2/QST3 merely because reactant and product structures are
available. Prefer QST only when endpoints are optimized, atom mapping and
stoichiometry match, conformers represent the same elementary step, and the
interpolation is chemically meaningful.

## Candidate Record

Store seeds and generated files as artifacts, link the operation to its Node,
and register only verified facts such as geometry, energy, convergence,
coordinate values, or provenance. Use a free versioned Evidence `kind` that
states what was observed.

A candidate that only satisfies target bond distances is not automatically a
saddle point or the intended reaction path. Inspect the complete local geometry
and available electronic diagnostics for contradictions. Later TS/Freq,
mode-assignment, connectivity, and any reaction-specific Gates remain separate.

## Recalculation

A technical retry may reuse the same scientific objective and immutable
submission identity only when the typed control result permits it. A changed
method, model chemistry, coordinate strategy, or scientific question should be
recorded as a new operation or Node chosen by the Root Agent. No special Node
category is required.
