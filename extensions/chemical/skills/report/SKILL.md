---
name: report
description: Build a reproducible calculation report from validated scientific Skill results and their source digests.
---

# Calculation report

Use this Skill for report tasks described above.

Run [scripts/build.py](scripts/build.py) through job_start, passing repeated `--result environment=path` entries and a new `--output-dir`. Stage the result files as inputs. Declare report.md and report.json as required outputs, register their Artifacts, then check every requested matrix cell is represented before calling the study complete. Failed or missing cells must be explained. Cross-method absolute energies are not accuracy rankings. Use the email Skill only for notifications the user requested.
