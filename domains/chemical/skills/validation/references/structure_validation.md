# Molecular Structure Contract

Structure comparison requires explicit chemical identity and geometry rules.
Verify the atom map before comparing coordinates by row order.

## Identity And Mapping

Verify element counts, charge, multiplicity/state, isotopes when relevant, and
one-to-one atom mapping. Mapping may come from stable atom order, explicit map
metadata, graph isomorphism, or a reviewed deterministic assignment. Ambiguous
symmetry-equivalent mappings remain a limitation.

## Alignment

Use Kabsch least-squares rigid alignment over the selected mapped atoms after
centering. Apply one proper rotation; do not allow reflection unless the
scientific comparison explicitly requests it. Report the aligned RMSD and the
atom subset/weights used.

After rigid alignment, compare bond
distances, angles, dihedrals, forming/breaking contacts, chirality, and basin
identity after alignment.

## Scientific Recording

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.

For endpoint identity, inspect fragment permutations, conformers, and
stereochemistry alongside the global RMSD and rendered structure.

## Execution boundary

There is no built-in mapped-structure comparison executor in this package.
Use an available analysis tool or implement a bounded script with explicit mapping,
atom selections and tolerances, then execute and register the result. Preserve
input digests and report symmetry ambiguity. `artifact_derive` records a descriptor;
it does not align structures or check stereochemistry.
