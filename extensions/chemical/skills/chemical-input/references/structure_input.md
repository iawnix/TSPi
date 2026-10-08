# Structure preparation

inspect --smiles checks the RDKit graph, formula, charge and unspecified stereo, not name identity.
seed --smiles --charge --multiplicity --output-dir generates explicit-H XYZ with a fixed ETKDG seed.
The output directory must be empty; incompatible electron-count/multiplicity parity is rejected.
Every XYZ has a SHA256 and isomer provenance. Use --enumerate-stereo for an explicitly scoped
set of alternatives; this does not confirm one stereochemical identity.
reaction --smiles accepts mapped reactants>>products and checks total elements, charge,
a bijection of explicit atoms, and lists bond changes. It does not verify that those changes
match an intended reaction class unless `--transformation` supplies a JSON object
with `kind=diels_alder` (diene/dienophile map IDs and forming_bonds) or `kind=explicit`
(bond_changes and optional hydrogen_changes). The DA check preserves every other bond
and every mapped atom's H count. Individual implicit-H correspondence and the
stereochemical mechanism remain unverified. Results use scoped `chemical-reaction/2` checks.
Single-molecule optimization does not require reaction mapping. Seeds and mappings do not
replace quantum calculations or mechanistic interpretation.
