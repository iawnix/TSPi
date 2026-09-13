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

Record mapping method, reference structure, selected atoms, RMSD, key internal
coordinates, stereochemical verdict, and source artifact digests as semantic
Observations. Use identity or stereochemical ProofSpecs when these values are
acceptance-critical.

For endpoint identity, inspect fragment permutations, conformers, and
stereochemistry alongside the global RMSD and rendered structure.

## Deterministic Tool Parameters

`ts_compare` exposes optional `parameters` with camel-case fields:

- `atomMapping`: one target index for every reference atom;
- `reactionCenterAtoms`: reference atom indices used for local RMSD;
- `keyBonds`, `keyAngles`, `keyDihedrals`: arrays of 2-, 3-, or 4-index checks;
- `stereochemicalChecks`: explicit `tetrahedral`, `alkene`, or `dihedral`
  checks with `retain`/`invert` policy; alkene checks also accept `E` or `Z`;
- `rmsdThreshold` and `reactionCenterThreshold`: finite values from 0 to 10
  angstrom.

Tetrahedral checks use `center` and four `neighbors`; alkene checks use two
`atoms` and two `substituents`; dihedral checks use four `atoms` and may set
`maxDeltaDegrees` from 0 to 180. The kernel rejects duplicate/out-of-range
indices, malformed type-specific fields, non-XYZ inputs, changed digests, and
closed output Nodes.
