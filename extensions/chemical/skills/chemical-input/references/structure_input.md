# Structure preparation

inspect --smiles checks the RDKit graph, formula, charge and unspecified stereo, not name identity.
seed --smiles --charge --multiplicity --output-dir generates explicit-H XYZ with a fixed ETKDG seed.
The output directory must be empty; incompatible electron-count/multiplicity parity is rejected.
Every XYZ has a SHA256 and isomer provenance. Use --enumerate-stereo for an explicitly scoped
set of alternatives; this does not confirm one stereochemical identity.
reaction --smiles accepts mapped reactants>>products and checks total elements, charge,
a bijection of explicit atoms, and bond changes. Implicit-H correspondence is not validated.
Single-molecule optimization does not require reaction mapping. Seeds and mappings do not
replace quantum calculations or mechanistic interpretation.
