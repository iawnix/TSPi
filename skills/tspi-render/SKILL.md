---
name: tspi-render
description: Produce deterministic visual artifacts from registered TSPi structures, reaction paths, and scientific curves for inspection, comparison, animation, and mechanism presentation.
---

# TSPi Rendering

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `ts_render` operations. Load `tspi-orchestration` for
workspace, artifact, activity, and evidence contracts. Rendering is a
presentation capability and does not establish a scientific conclusion.

## Operating Rules

- Resolve input artifacts through `ts_state mode=artifacts`; never construct
  workspace paths from user text.
- Keep the owning ResearchNode, logical artifact IDs, output name, and selected
  operation explicit.
- Treat `render`, `animate`, `compare`, `mechanism`, `curve`, `energy`, `scan`, and
  `convergence` as separate operations
  with their own input-count and output-format requirements.
- Curve operations consume one `ts-curve-data/1` JSON artifact and emit a PNG.
  They are presentation only; numeric values must remain traceable to the source
  artifact.
- Inspect the output and its digest, but record scientific values through
  verified primary artifacts and normal `ts_change` Decisions.

Read `references/render_contract.md` for request validation, output ownership,
renderer limits, and failure handling.
