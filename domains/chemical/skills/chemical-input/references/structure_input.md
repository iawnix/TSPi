# Structure preparation

inspect --smiles checks the RDKit graph, formula, charge and unspecified stereo.
seed --smiles --charge --multiplicity --output-dir generates explicit-H XYZ with a fixed ETKDG seed.
The output directory must be empty; incompatible electron-count/multiplicity parity is rejected.
Every XYZ has a SHA256 and isomer provenance. Select a stereoisomer based on the task or
use --enumerate-stereo to study alternatives. Source=llm requires no separate confirmation.
reaction --smiles accepts mapped reactants>>products and checks total elements, charge,
a bijection of explicit atoms, and lists bond changes. It does not verify that those changes
match an intended reaction class unless `--transformation` supplies a JSON object
with `kind=diels_alder` (diene/dienophile map IDs and forming_bonds) or `kind=explicit`
(bond_changes and optional hydrogen_changes). The DA check preserves every other bond
and every mapped atom's H count. Individual implicit-H correspondence and the
stereochemical mechanism remain unverified. Results use scoped `chemical-reaction/2` checks.
Single-molecule optimization does not require reaction mapping. Seeds and mappings do not
replace quantum calculations or mechanistic interpretation.

## Compare structures

inspect and seed include a `chemical-identity/1` object with canonical isomeric SMILES,
charge, RDKit version and content identity. Register the chosen target as an Artifact
and reference it through the Node's `subjects.target`.
Prepare `chemical.compare@1` with `--input target=<inspect.json>` and
`--input actual=<structure.json-or-geometry.xyz>`. For XYZ add
`-- --actual-format xyz --charge <actual-charge>`; structure JSON is the default.
Collect `results/comparison.json`, which reports match, mismatch or indeterminate,
the compared structures and the scope of the checks. XYZ bond orders are inferred.
Record the findings with `check_refs` and distinguish target/calculated `subjects`.
Use differences to guide the research; checks do not gate publication or further work.
