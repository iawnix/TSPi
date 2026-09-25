# Render Contract

`artifact.render` creates molecular images, animations, comparison panels, reaction
diagrams, and scientific curves as local artifacts.

The request selects `render`, `animate`, `compare`, `mechanism`, `curve`, `energy`,
`scan`, or `convergence`, one existing
ResearchNode, logical input artifact IDs, and a safe output filename. The host
resolves paths/digests and owns:

```text
nodes/<node_id>/outputs/render/<outputName>
```

Use registered workspace artifacts, the operation's required input
count, and a new filename ending in `.gif` for animation or `.png` for other
operations. The host checks path containment, file type, input availability,
and output names. A successful backend produces a non-empty regular PNG/GIF
whose digest is returned through the artifact catalog.

Curve operations require exactly one JSON input conforming to `ts-curve-data/1`
and always produce a PNG. The artifact contains one to sixteen series,
with equal finite `x` and `y` arrays (maximum 100,000 points per series).

For example, a scan-data artifact can contain:

```json
{
  "schema_version": "ts-curve-data/1",
  "title": "Bond-distance scan",
  "x_label": "C–C distance (angstrom)",
  "x_unit": "angstrom",
  "y_label": "Energy relative to first point (kJ/mol)",
  "y_unit": "kJ/mol",
  "series": [{"name": "Scan", "x": [1.5, 1.8, 2.1], "y": [0.0, 12.5, 30.2]}]
}
```

These illustrative numbers show the data format. For a study, use values from
verified calculation outputs and retain their units and reference energy.
Select the registered JSON artifact ID as the input for `scan`; `curve`,
`energy`, and `convergence` accept the same data format.

Molecular operations use `xyzrender`, and curve operations use Matplotlib.
The schema is [curve-data.schema.json](../../../contracts/ts-render/curve-data.schema.json).

Use rendering to inspect geometry, compare structures, animate modes, or
communicate a mechanism. Establish bond changes, endpoint identity, and mode
assignments from the corresponding structural and calculation data. Record
verified values as Findings with primary source artifacts.
