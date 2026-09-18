# TSPi research architecture figure

Files:

- `tspi-research-architecture.svg`: editable vector artwork for manuscripts and web pages.
- `tspi-research-architecture.pdf`: one-page landscape vector export at 183 mm × 109.8 mm (full-width figure for common two-column journal layouts).
- `tspi-research-architecture.tif`: 600 dpi raster export (4326 × 2592 px) for submission systems that require TIFF.
- `tspi-research-architecture.drawio`: editable Draw.io source for later layout or label changes.
- `tspi-mechanism-framework.svg`: chemistry-focused vector framework for the main text or methods overview.
- `tspi-mechanism-framework.pdf`: one-page vector export at 183 mm × 112 mm.

Suggested figure caption:

> **Figure X. Abstract architecture of the TSPi transition-state research workflow.** The Root Agent proposes scientific questions, hypotheses, methods, and explicit decisions. A deterministic Research Kernel is the single mutation authority for the Phase–Node–Claim graph, provenance ledger, and declarative validation records. Bounded capability adapters produce artifacts and parser candidates; only verified evidence is promoted to immutable Observations and evaluated by frozen ProofSpecs. Validated outcomes, open findings, and backtracking decisions feed the next research step. TS Web consumes scoped projections, while Phone/terminal clients connect to the shared Pi session and invoke the Agent and tools; neither becomes a second scientific state store.

The artwork uses a restrained color-blind-aware palette: teal for canonical state, navy for data flow, amber for bounded capabilities, violet for provenance, coral for validation and decision feedback, and blue for the evidence plane. TS Web is the read-only projection; Phone and terminal are equal interactive Pi clients and may prompt the shared App Server, invoke tools, and receive tool results. It is intentionally abstract and uses short labels so it can serve as a main-text architecture figure rather than a software flowchart. The source viewBox is 1200 × 720; main section labels remain 14 units or larger, with compact registry labels reduced only where needed to stay inside their cards.

Open the `.drawio` file in [diagrams.net](https://app.diagrams.net/) and export to SVG/PDF when typography or journal page dimensions need to be adjusted. The SVG and Draw.io XML were checked by parser validation; the PDF is one 183 mm × 109.8 mm page with embedded fonts. A rendered preview and the 4326 × 2592 px, 600 dpi TIFF export were also inspected.

## Chemistry-focused framework

`tspi-mechanism-framework.svg` is a flat, editable SVG sized for a 183 mm-wide
landscape figure. It separates the scientific state owned by the Research Kernel
from the execution and evidence planes. The intended caption is:

> **Figure X. TSPi framework for auditable reaction-mechanism research.** A Root Agent formulates a Claim/Hypothesis together with falsifiers and a stopping rule. The Research Kernel creates bounded Research Nodes, records provenance, and is the sole mutation boundary. Skills and plugins execute geometry generation, transition-state optimization, frequency/IRC checks, and path comparisons, producing inspectable artifacts rather than scientific conclusions. After Root verification, artifacts are promoted to Observations or Findings. A NodeGate closes an individual research task, whereas a ClaimGate evaluates whether the accumulated evidence supports, refutes, or leaves the Claim open. The resulting interpretation determines the next dependent Node, branch, or backtracking step; the Research Map is a read-only projection of this history.

For journals that require TIFF, export the SVG at its native aspect ratio without
rasterizing text; the viewBox is `1600 × 980` and the physical canvas is
`183 × 112 mm`.
