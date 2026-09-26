---
name: tspi-render
description: Render molecular structures, trajectories, reaction mechanisms, and scientific curves as TSPi figures and animations.
---

# TSPi Rendering

[Chinese version](SKILL.zh-CN.md)

Use this Skill with `artifact.render` to turn registered structures and numerical
Artifacts into figures. Use `tspi-research-kernel` for Node ownership and map
changes.

Do not treat a rendered image as new scientific evidence. Verify the source
Artifact, labels, units, and revision before citing the figure in a Finding.

| Operation | Inputs | Output |
| --- | --- | --- |
| `render` | one molecular structure | PNG |
| `animate` | one trajectory | GIF |
| `compare` | two or more structures | PNG panels |
| `mechanism` | reactant, transition state, product | PNG diagram |
| `curve`, `energy`, `scan`, `convergence` | `ts-curve-data/1` JSON | PNG plot |

Resolve input IDs with `research.read mode=artifacts`, choose the owning Node and a
safe output name, run `artifact.render`, and inspect the returned Artifact and digest.
Check labels, units, references, and numerical values against the source. A
figure is a presentation Artifact; record scientific numbers as
`FactFinding` only when they were verified from the source data. Read [render_contract.md](references/render_contract.md).
