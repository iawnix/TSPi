# Figures and report production

## Content and data

Answer the research question first, then explain methods, key findings, evidence
strength, missing data, and next steps. Include requested comparisons even when
tasks failed or remain incomplete; missing values are not zero.
Build CSV/JSON data from actual results with structure/state labels, method/basis,
solvent, charge/multiplicity, energy type and units, validation status, and source
file or Artifact references. For thermodynamic quantities, record temperature,
standard state, and correction scheme. Preserve source digests, the exact fields
used for plotting, and the plotting script.

## Choose figures

| Evidence | Useful display | Required labels |
| --- | --- | --- |
| Reactant, intermediate, candidate saddle, product geometries | Molecular images or comparison panels | Structure labels, key atom indices/distances, validation status |
| Stationary-point energies with a common reference | Relative energy profile | Zero reference, energy type, units, method, verified connections |
| Coordinate scan or IRC points | Energy against reaction coordinate | Coordinate definition/units, direction, convergence, missing points |
| Methods or conformers | Numerical table, dot plot, or bars | Comparison basis, reference, method/environment |
| Frequencies or dynamics | Spectrum, time series, or trajectory snapshots | Frequency/time units, sampling range, data sources |

Render molecular images from actual coordinates. Add reaction or study diagrams
when useful, labeling schematics separately from calculation evidence.
Environment labels identify compute locations, not distinct scientific methods.

## Energy plots

Within each comparable group, compute `ΔE_i = E_i - E_ref`. Convert Hartree to
kJ/mol with `2625.49964` or kcal/mol with `627.50947`. Preserve original values and
name the reference state. Keep electronic energy, zero-point-corrected energy,
enthalpy, and Gibbs free energy separate rather than joining them in one curve.
Direct comparisons require consistent composition/stoichiometry, method,
electronic state, and thermodynamic conditions. For reactions with differing
molecule counts, sum reference energies stoichiometrically and explain standard
state treatment. Use a separate reference for each method.

Display stationary points as discrete levels or clearly schematic connections;
do not present an interpolated line as a calculated continuous path. Plot actual
scan/IRC points against their real coordinates without hiding failed points.
Mark unvalidated candidates with open symbols, dashed lines, or text rather than
labeling them confirmed TS structures. Error bars require actual uncertainty or
repeat evidence. Claim connected stationary points only with path evidence.
If comparable data are missing, explain the gap and report available tables;
do not fabricate a curve.

## Production and verification

Keep `data/`, `figures/`, and plotting scripts in the report directory. Use an
available plotting library such as Matplotlib to generate SVG/PNG, preserving
numerical data for reproduction. Plotting existing results needs no new
scientific executor; use a generic Job when a managed environment is needed.
Do not assume the minimal Host Python includes scientific plotting libraries.

Embed figures using Markdown image syntax and relative paths such as `figures/energy-profile.svg`,
and provide a caption with figure number, reference state, method, interpretation,
and source references. Keep labels readable, units and legends complete, and
colors distinguishable in grayscale. Tables and figures should share one data
source and use justified significant figures.

Open the exported document and every figure to check actual image display,
pagination/cropping, fonts, captions, links, values, and provenance. Register the
final document, images, tables, and scripts; preserve relative paths for offline
reading. If conversion tools are unavailable, state the delivered format and do
not claim an unproduced PDF/HTML file exists.
