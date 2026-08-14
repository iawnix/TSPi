# Render Contract

`ts_render` creates visual artifacts from molecular structures and trajectories.

Supported public CLI shapes:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/transition-state-workflow
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" diagnostic --json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" render input.xyz -o nodes/n001/outputs/render.png
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" compare r.xyz ts.xyz p.xyz -o nodes/n001/outputs/compare.png
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" animate irc.xyz -o nodes/n001/outputs/irc.gif
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" mechanism r.xyz ts.xyz p.xyz -o nodes/n001/outputs/mechanism.png
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

- edit `research_state.json`, `claims.json`, `evidence.json`,
  `gate_results.json`, or `decision_log.jsonl`;
- close nodes or set scientific verdicts;
- claim candidate, TS/Freq, connectivity, accepted-TS, or pathway success;
- infer mechanism validity from a rendered image.

To make a render visible as workspace evidence, create the artifact first and
then register it through `ts_workspace update_workspace` with a decision JSON.
Use evidence fields such as:

```json
{
  "schema_version": "ts-evidence/2",
  "evidence_id": "ev_n001_render_001",
  "node_id": "n001",
  "kind": "render_artifact/1",
  "evidence_tier": "local_compute",
  "summary": "Rendered local structure view.",
  "facts": {"render_completed": true},
  "artifact_refs": ["nodes/n001/outputs/render.png"],
  "provenance": {"producer": "ts_render", "producer_version": null, "source_sha256": null}
}
```
