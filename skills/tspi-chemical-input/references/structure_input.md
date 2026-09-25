# Confirmed Structure Input

Use a confirmed isomeric SMILES with explicit charge and multiplicity for
`artifact.seed`. Review unassigned stereochemistry and the generated 3D seed before
using it as a calculation input. For reactions, run `reaction.parse`, balance
the closed system, generate mapping candidates, and explicitly select a
mapping before extracting bond changes.
