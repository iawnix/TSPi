---
name: report
description: Write illustrated research reports from evidence, with molecular structures, energy plots, data tables, methods, conclusions, and traceable sources.
---

# Research reports

Answer the user's research question with conclusions, evidence, methods, and
limitations, using the requested language and delivery format. A full report
should combine text and visuals: molecular images when structures are available,
energy plots for comparable energies, and tables of values and validation status.
Choose visuals from actual data; never invent structures, paths, energies, or
error bars to fill a layout.

Read [figures and report production](references/illustrated_report.md) to prepare
reproducible data tables, plotting scripts, images, and the final document.
Markdown with an image directory is a usable default; export HTML/PDF or other
requested formats with available tools. Embed figures with captions in the
report itself rather than providing only a list of image paths.

## Basic evidence table

For existing `science-result` files, invoke [scripts/build.py](scripts/build.py)
through native bash:

```bash
"$RESEARCH_AGENT_PYTHON" <installed-report-skill>/scripts/build.py --result local=<workspace>/path/to/result.json --output-dir <workspace>/reports/comparison-v1
```

Pass one `--result environment=path` per result and use a new or empty output
directory. This helper produces a basic `report.md` table and `report.json` source
digests; it does not automatically produce energy plots, molecular images, or a
scientific narrative. Read its outputs, then complete the research question,
evidence analysis, figures, and conclusions. For other source formats, build a
report dataset directly from the collected materials.

## Images and delivery

For molecular images, use `chemical.render@1` with input role `geometry=<XYZ file>`
and an environment with the `render` binding. The Job produces SVG, PNG, and a
source-digest record; options include `--style`, `--size`, `--charge`, and
`--multiplicity`. Rendering depicts supplied coordinates; an image does not
establish optimization, connectivity, or transition-state validity.

Use file and scripting tools to assemble existing results; additional scientific
calculations use `job_*`. Plot with an available library, and run rendering Jobs
in their configured environments. Open the final document and images to check
links, axes, captions, units, tables, and provenance. Register the report and its
figures, data, and scripts as materials and cite them in the research conclusion.
Use the email Skill for delivery only with sending authorization.
