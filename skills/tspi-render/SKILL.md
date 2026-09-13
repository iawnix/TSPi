---
name: tspi-render
description: Render molecular structures, trajectories, reaction mechanisms, and scientific curves as TSPi figures and animations.
---

# TSPi Rendering

[Chinese version](SKILL.zh-CN.md)

Use this Skill to turn structures and numerical data into figures with
`ts_render`. Load `tspi-orchestration` for workspace and artifact operations.

## Choose An Output

| Operation | Inputs | Output |
| --- | --- | --- |
| `render` | One molecular structure | PNG molecular image |
| `animate` | One trajectory | GIF animation |
| `compare` | Two or more structures | PNG comparison panels |
| `mechanism` | Three structures ordered reactant, transition state, product | PNG reaction diagram |
| `curve`, `energy`, `scan`, `convergence` | One `ts-curve-data/1` JSON artifact | PNG scientific plot |

## Rendering Workflow

1. Resolve registered input IDs through `ts_state mode=artifacts`.
2. Select the operation, owning ResearchNode, input order, and a new output
   filename with the appropriate extension.
3. For curves, check series names, axis labels, units, and numerical values
   against the source data. Keep energy references and scan coordinates explicit.
4. Run `ts_render` and inspect the figure, returned artifact ID, and digest.
5. Record scientific values as Observations citing verified source artifacts;
   use the generated figure in the response or a `tspi-report` report.

Molecular rendering uses `xyzrender`; curve rendering uses Matplotlib.
Input formats, curve examples, output paths, and error handling are described
in [the render reference](references/render_contract.md).
