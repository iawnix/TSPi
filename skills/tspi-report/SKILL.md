---
name: tspi-report
description: Build TSPi research reports with conclusions, supporting evidence, calculation history, validation results, and visual assets.
---

# TSPi Reports

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `ts_report`. Load `tspi-orchestration` for workspace state,
artifact identity, validation, and Decision contracts. Load `tspi-render` when
the report requires visual assets.

## Operating Rules

- Build a report only from a complete valid workspace and registered logical
  artifact IDs.
- Keep scientific revision, operational revision, acceptance status, Findings,
  limitations, and open questions distinct.
- Record the current Node and Claim status through `ts_change` before building the report;
  include ongoing work and open questions when reporting interim progress.
- Cite current Observation, ProofSpec, ValidationResult, Finding, and source
  artifact references for every scientific statement.
- Create a new report package for each export and verify its files and revisions
  against the manifest before returning it.

Read [report_template.md](references/report_template.md) for the required projection, acceptance
language, numerical discipline, and package-integrity rules.
