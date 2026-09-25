# TSPi mechanism framework figure

[English](README.md) | [简体中文](README.zh-CN.md)

Files:

- `tspi-mechanism-framework.svg`: editable chemistry-focused vector framework.
- `tspi-mechanism-framework.pdf`: one-page vector export at 183 mm × 112 mm.

`tspi-mechanism-framework.svg` is a flat, editable SVG sized for a 183 mm-wide
landscape figure. It separates the scientific state owned by the Research Kernel
from the execution and evidence planes. The intended caption is:

> **Figure X. Example application: auditable reaction-mechanism research with TSPi.** A Root Agent formulates a Claim together with falsifiers and a stopping rule. The domain-neutral Research Kernel creates bounded Research Nodes from explicit ChangeSets, records provenance, and is the sole mutation boundary. Chemistry Skills and plugins execute geometry generation, transition-state optimization, frequency/IRC checks, and path comparisons, producing inspectable artifacts rather than scientific conclusions. After Root verification, artifacts become FactFindings or IssueFindings in the map. A NodeGate controls whether an individual research task may close as completed, whereas a ClaimGate evaluates accumulated Findings. Root explicitly records the resulting Claim status and chooses the next dependent Node, branch, or backtracking step; the ResearchMap is the canonical state rendered by clients.

For journals that require TIFF, export the SVG at its native aspect ratio without
rasterizing text; the viewBox is `1600 × 980` and the physical canvas is
`183 × 112 mm`.
