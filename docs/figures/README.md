# TSPi research architecture figure

Files:

- `tspi-research-architecture.svg`: editable vector artwork for manuscripts and web pages.
- `tspi-research-architecture.pdf`: one-page landscape vector export at 183 mm × 109.8 mm (full-width figure for common two-column journal layouts).
- `tspi-research-architecture.tif`: 600 dpi raster export (4326 × 2592 px) for submission systems that require TIFF.
- `tspi-research-architecture.drawio`: editable Draw.io source for later layout or label changes.

Suggested figure caption:

> **Figure X. Abstract architecture of the TSPi transition-state research workflow.** The Root Agent proposes scientific questions, hypotheses, methods, and explicit decisions. A deterministic Research Kernel is the single mutation authority for the Phase–Node–Claim graph, provenance ledger, and declarative validation records. Bounded capability adapters produce artifacts and parser candidates; only verified evidence is promoted to immutable Observations and evaluated by frozen ProofSpecs. Validated outcomes, open findings, and backtracking decisions feed the next research step. TS Web and Phone/terminal clients consume scoped projections and do not become a second scientific state store.

The artwork uses a restrained color-blind-aware palette: teal for canonical state, navy for data flow, amber for bounded capabilities, violet for provenance, coral for validation and decision feedback, and blue for the evidence plane. It is intentionally abstract and uses short labels so it can serve as a main-text architecture figure rather than a software flowchart. The source viewBox is 1200 × 720; key labels use a minimum 14-unit size so they remain legible after reduction to the target physical width.

Open the `.drawio` file in [diagrams.net](https://app.diagrams.net/) and export to SVG/PDF when typography or journal page dimensions need to be adjusted. The SVG and Draw.io XML were checked by parser validation; the PDF is one page with embedded Inter fonts and a 519.12 × 311.04 pt page (183 mm × 109.8 mm). A Chromium preview and a 600 dpi TIFF export were also inspected.
