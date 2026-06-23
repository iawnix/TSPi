# Render Contract

`ts_render` creates visual artifacts from molecular structures and trajectories.

Supported public CLI shapes:

```bash
python scripts/ts_render.py diagnostic --json
python scripts/ts_render.py render input.xyz -o nodes/n001/outputs/render.png
python scripts/ts_render.py compare r.xyz ts.xyz p.xyz -o nodes/n001/outputs/compare.png
python scripts/ts_render.py animate irc.xyz -o nodes/n001/outputs/irc.mp4
python scripts/ts_render.py mechanism r.xyz ts.xyz p.xyz -o nodes/n001/outputs/mechanism.png
```

Allowed behavior:

- read input structures or trajectories;
- call the configured `xyzrender` executable;
- create node-scoped image, animation, or diagnostic artifacts;
- return a structured `RenderResult`.

Render dependency boundary:

- `xyzrender` is the only render backend.
- Blender, FFmpeg, OpenBabel, Mayavi, and PyVista are not required or probed by
  `ts_render`.

Forbidden behavior:

- edit `manifest.json`, `tree.json`, `mechanism_model.json`,
  `pathway_model.json`, `evidence_registry.json`, or `decision_log.jsonl`;
- close nodes or set scientific verdicts;
- claim candidate, TS/Freq, connectivity, accepted-TS, or pathway success;
- infer mechanism validity from a rendered image.

To make a render visible as workspace evidence, create the artifact first and
then register it through `ts_workspace update_workspace` with a decision JSON.
Use evidence fields such as:

```json
{
  "kind": "render_artifact",
  "role": "visualization",
  "evidence_tier": "local_compute",
  "path": "nodes/n001/outputs/render.png"
}
```
