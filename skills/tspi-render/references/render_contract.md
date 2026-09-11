# Render Contract

`ts_render` is a deterministic local visualization tool. It starts no child
model and performs no scientific inference.

The request selects `render`, `animate`, `compare`, `mechanism`, `curve`, `energy`,
`scan`, or `convergence`, one existing
ResearchNode, logical input artifact IDs, and a safe output filename. The host
resolves paths/digests and owns:

```text
nodes/<node_id>/outputs/render/<outputName>
```

It rejects unknown Nodes/artifacts, wrong input count, absolute/traversing paths,
symlink components, missing files, unsafe names, extension mismatch, and
overwrite. A successful backend must produce a non-empty regular PNG/GIF whose
digest is returned through the artifact catalog.

Curve operations require exactly one JSON input conforming to `ts-curve-data/1`
and always produce a PNG. The artifact contains one to sixteen named series,
with equal finite `x` and `y` arrays (maximum 100,000 points per series).

Use rendering to inspect geometry, compare structures, animate modes, or
communicate a mechanism. Do not infer a bond, endpoint identity, mode
assignment, or accepted Claim from appearance alone. Record verified numerical
or structural values as normal Observations with primary source artifacts.
