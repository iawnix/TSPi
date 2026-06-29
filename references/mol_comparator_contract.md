# Molecular Comparator Contract

`mol_comparator` is a pure structure comparison toolkit.

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
    "heavy_atom_rmsd": 0.18,
    "reaction_center_rmsd": 0.07,
    "key_bonds": [],
    "stereochemistry": []
  },
  "diagnostics": []
}
```

`stereochemical_checks` supports explicit tetrahedral, alkene, and dihedral
checks using zero-based atom indices. A failed declared check makes the
comparator verdict `mismatched` even when RMSD and bond metrics are acceptable.

The comparator never writes workspace ledgers and never accepts a TS. Its result
can be registered as evidence through `update_workspace`.
