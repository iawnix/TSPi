---
name: report
description: Build a reproducible calculation report from validated scientific Skill results and their source digests.
---

# Calculation report

Use this Skill for report tasks described above.

Use native bash to invoke the installed [scripts/build.py](scripts/build.py) with bounded execution time:

```bash
"$TSPI_PYTHON" <installed-report-skill>/scripts/build.py --result local=<workspace>/path/to/result.json --output-dir <workspace>/reports/comparison-v1
```

Resolve the script from this Skill's listed location. Repeat `--result environment=path` for each collected scientific result. Use a new missing or empty output directory; the builder refuses to overwrite existing files. Report formatting uses existing results and creates no Job or calculation Attempt. Additional scientific computation still uses job_*.

Read report.md and report.json, verify source digests and every requested matrix cell, then register both files as Artifacts associated with the report Node. Explain failed or missing cells; do not invent results. Cross-method absolute energies are not accuracy rankings. Use the email Skill through bash for user-requested delivery, then close the delivery Node and record the final checkpoint. Global blocked/terminal requires an explicit recovery checkpoint before further writes.
