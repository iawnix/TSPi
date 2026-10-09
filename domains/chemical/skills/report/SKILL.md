---
name: report
description: Build calculation reports from supplied scientific results, or render supplied XYZ geometries as SVG and PNG images.
---

# Calculation report

Use native bash to invoke the installed [scripts/build.py](scripts/build.py) with bounded execution time:

```bash
"$RESEARCH_AGENT_PYTHON" <installed-report-skill>/scripts/build.py --result local=<workspace>/path/to/result.json --output-dir <workspace>/reports/comparison-v1
```

Resolve the script from this Skill's listed location. Repeat `--result environment=path` for each collected scientific result. Use a new missing or empty output directory; the builder refuses to overwrite existing files. Report formatting uses existing results and creates no Job or calculation Job. Additional scientific computation still uses job_*.

Read report.md and report.json, verify source digests and every requested method/environment combination, then register both materials. Explain failures, missing results and method limitations. Cross-method absolute energies are not accuracy rankings. Use the email Skill for authorized delivery, retain receipts and record progress with research_update.

For molecular images, prepare `chemical.render@1` with input role `geometry=<XYZ file>` and an environment with the `render` binding. The declared entry produces SVG, PNG and a source-digest record through a Job. Optional arguments are `--style`, `--size`, `--charge` and `--multiplicity`; the renderer uses the supplied coordinates. An image does not prove optimization, connectivity or transition-state validity. Text report formatting above remains independent of rendering dependencies.
