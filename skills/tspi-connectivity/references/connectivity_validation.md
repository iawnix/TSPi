# Connectivity Validation

Connectivity asks whether a candidate path reaches the reactant and product
basins declared by the target Claim. It is distinct from stationary-point and
imaginary-mode validation.

## Required Observations

The built-in `connectivity@1` template uses semantic concepts for one subject:

- normal program termination;
- bidirectional path completion;
- no recorded path program failures;
- reverse endpoint assignment equals the declared reactant ref;
- forward endpoint assignment equals the declared product ref.

Endpoint assignments use direction qualifiers. Record the source path and any
endpoint optimization artifacts with exact digests.

## Finite Paths

To assign a finite IRC endpoint to a basin, inspect the last
geometry/gradient, optimize the endpoint when needed, compare it with reference
basins using a valid atom map, and expose any short-path or maximum-step limit.
An assignment with unresolved identity ambiguity should remain inconclusive or
produce a blocking Finding.

## Deterministic Evaluation

Freeze the connectivity ProofSpec against the target Claim and declared
reactant/product refs before evaluation. Select exact Observation refs. Missing
direction, missing endpoints, conflicting assignments, or incomplete paths
require further evidence or a Finding before acceptance.

Add identity, stereochemistry, state-character, or electronic-structure
ProofSpecs when the Claim needs them. They are additional dimensions under the
same engine.

## Acceptance

The built-in `accepted-ts@3` profile requires stationary-point,
reaction-coordinate, and connectivity dimensions. Acceptance also covers every
other ProofSpec attached to the Claim and rejects open blocking Findings.
