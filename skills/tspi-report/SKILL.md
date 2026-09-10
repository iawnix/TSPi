---
name: tspi-report
description: Build deterministic evidence-bound TSPi report packages that project scientific and operational state without changing the workspace.
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
- Treat reports as projections and delivery artifacts; they cannot repair,
  complete, or accept a ResearchNode.
- Cite current Observation, ProofSpec, ValidationResult, Finding, and source
  artifact references for every scientific statement.
- Require a new no-overwrite report package whose manifest matches its files and
  revisions before returning it.

Read `references/report_template.md` for the required projection, acceptance
language, numerical discipline, and package-integrity rules.
