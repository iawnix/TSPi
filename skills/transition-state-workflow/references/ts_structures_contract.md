# TS Structures Contract

`ts_structures` is a pure structure comparison toolkit.

Inputs should be explicit:

- reference structure;
- target structure;
- atom mapping;
- reaction center atoms;
- key bonds, angles, and dihedrals;
- conformer policy;
- stereochemical policy via explicit `stereochemical_checks`.

Output shape:

```json
{
  "verdict": "matched",
  "uncertainty": "low",
  "metrics": {
    "alignment": {
      "method": "kabsch",
      "fit_selection": "heavy_atoms",
      "fit_atom_count": 12,
      "reflection_allowed": false
    },
    "heavy_atom_rmsd": 0.18,
    "reaction_center_rmsd": 0.07,
    "key_bonds": [],
    "stereochemistry": []
  },
  "diagnostics": []
}
```

The comparator validates that `atom_mapping` is a one-to-one, element-preserving
mapping from reference indices to target indices. It fits one proper-rotation
Kabsch transform on mapped heavy atoms (or all atoms when no heavy atoms exist),
then applies that same transform to the complete target structure before both
heavy-atom and reaction-center RMSDs are calculated. Mirror reflection is never
an allowed alignment operation.

`stereochemical_checks` supports explicit tetrahedral, alkene, and dihedral
checks using zero-based atom indices. A failed declared check makes the
comparator verdict `mismatched` even when RMSD and bond metrics are acceptable.

The structure toolkit never writes workspace state files and never accepts a TS. Its result
can be registered as evidence through `update_workspace`.
