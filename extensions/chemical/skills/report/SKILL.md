---
name: report
description: Build calculation reports from supplied scientific results, or render supplied XYZ geometries as SVG and PNG images.
---

# Calculation report

Use native bash to invoke the installed [scripts/build.py](scripts/build.py) with bounded execution time:

```bash
"$TSPI_PYTHON" <installed-report-skill>/scripts/build.py --result local=<workspace>/path/to/result.json --output-dir <workspace>/reports/comparison-v1
```

Resolve the script from this Skill's listed location. Repeat `--result environment=path` for each collected scientific result. Use a new missing or empty output directory; the builder refuses to overwrite existing files. Report formatting uses existing results and creates no Job or calculation Attempt. Additional scientific computation still uses job_*.

Read report.md and report.json, verify source digests and every requested matrix cell, then register both files as Artifacts associated with the report Node. Explain failed or missing cells; do not invent results. Cross-method absolute energies are not accuracy rankings. Use the email Skill through bash for user-requested delivery, then close the delivery Node and record the final checkpoint. Global blocked/terminal requires an explicit recovery checkpoint before further writes.

For collected scientific Jobs prefer repeated `--job <workspace>/runs/jobs/<job_id>` arguments; the builder derives the compute environment and result location from Job records. For standalone `--result environment=path`, the left side is the actual compute environment (for example local), never a method label. Register report.md and report.json, then follow the email Skill's receipt registration and delivery Gate procedure.

For molecular images, prepare `chemical.render@1` with input role `geometry=<XYZ file>` and an environment with the `render` binding. The declared entry produces SVG, PNG and a source-digest record through a Job. Optional arguments are `--style`, `--size`, `--charge` and `--multiplicity`; the renderer uses the supplied coordinates. An image does not prove optimization, connectivity or transition-state validity. Text report formatting above remains independent of rendering dependencies.
