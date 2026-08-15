# Render Contract

`ts_render` is a deterministic local visualization tool. It starts no child
model and performs no scientific inference.

The request selects `render`, `animate`, `compare`, or `mechanism`, one existing
ResearchAct, logical input artifact IDs, and a safe output filename. The host
resolves paths/digests and owns:

```text
acts/<act_id>/outputs/render/<outputName>
```

It rejects unknown Acts/artifacts, wrong input count, absolute/traversing paths,
symlink components, missing files, unsafe names, extension mismatch, and
overwrite. A successful backend must produce a non-empty regular PNG/GIF whose
digest is returned through the artifact catalog.

Use rendering to inspect geometry, compare structures, animate modes, or
communicate a mechanism. Do not infer a bond, endpoint identity, mode
assignment, or accepted Claim from appearance alone. Record verified numerical
or structural values as normal Observations with primary source artifacts.
