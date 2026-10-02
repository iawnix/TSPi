# Connectivity Validation

Connectivity asks whether a candidate path reaches the reactant and product
basins declared by a Claim. It is distinct from stationary-point and
imaginary-mode checks.

## Checklist

For each direction, inspect normal program termination, path completion, the
last geometry and gradient, endpoint optimization when needed, and endpoint
assignment against the declared reactant or product Artifact. Keep direction,
source path, endpoint optimization, and digest references explicit.

Verify atom mapping, element counts, charge, multiplicity/state, relevant
isotopes, bond changes, internal coordinates, stereochemistry, and any
short-path or maximum-step limitation. Use `artifact_compare` for deterministic
geometry and stereochemical checks.

## Recording And Evaluation

Record verified assignments, mapping, RMSD, coordinates, and source references
as `FactFinding`. Missing direction, endpoints, path completion, or identity
evidence becomes an `IssueFinding`. Conflicting assignments are also an
IssueFinding with both source refs. Findings inform, but do not automatically
change, Node state or Claim status.

Create a NodeGate or ClaimGate only when a criterion such as endpoint identity,
path completion, or stereochemical retention needs a visible verdict. Evaluate
it with the current evidence refs; the Gate does not change Claim status.
