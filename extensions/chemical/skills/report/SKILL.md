---
name: report
description: Build a reproducible calculation report from validated scientific Skill results and their source digests.
---

# Calculation report

Use this Skill for report tasks described above.

Prepare the request with [scripts/prepare_job.py](scripts/prepare_job.py):

```bash
"$TSPI_PYTHON" scripts/prepare_job.py --result local=path/to/result.json --output prepared/report-job.json
```

Use the installed Skill script path when invoking the helper. Repeat `--result environment=path` for each result. The helper uses the installed local `TSPI_PYTHON`, stages the report builder and every input, and prints `requestFile` plus `requestSha256`. Pass those fields and the report `nodeId` to `job_start`. The report Node must have a strategy and satisfied dependencies before submission.

Job cwd is an isolated `runs/jobs/<job_id>` directory. Commands and declared outputs use paths relative to that directory; an optional cwd must be a relative subdirectory. Source inputs may be absolute or workspace-relative. Do not use an absolute workspace directory as cwd or output path. The helper declares `results/report.md` and `results/report.json`; the builder accepts a missing or empty output directory and refuses a nonempty directory. Use a new `--work-id` for an intentional rerun.

Collect the Job outputs and register their Artifacts, then check every requested matrix cell is represented before calling the study complete. Failed or missing cells must be explained. Cross-method absolute energies are not accuracy rankings. Use the email Skill only for notifications the user requested.
