# Molecular Structure Contract

Structure comparison requires explicit chemical identity and geometry rules.
Never compare coordinates by raw row order unless the atom map is verified.

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

Do not use alignment to erase meaningful internal differences. Compare bond
distances, angles, dihedrals, forming/breaking contacts, chirality, and basin
identity after alignment.

## Scientific Recording

Record mapping method, reference structure, selected atoms, RMSD, key internal
coordinates, stereochemical verdict, and source artifact digests as semantic
Observations. Use identity or stereochemical GateSpecs when these values are
acceptance-critical.

A visually similar render or low global RMSD does not prove endpoint identity,
especially for fragment permutations, conformers, or stereochemical inversion.
