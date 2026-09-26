---
name: tspi-report
description: Build TSPi research reports from the canonical ResearchMap, calculation history, Findings, and visual Artifacts.
---

# TSPi Reports

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `report_build`. Use `tspi-research-kernel` for ResearchMap
semantics, `tspi-orchestration` for workflow history, and `tspi-render` when a
report needs figures.

Build from a valid workspace and registered logical Artifact IDs. Show the
current ResearchMap revision, Claims, Node states and outcomes,
FactFindings, IssueFindings, Gate criteria/evaluations, open questions, and
calculation history as distinct sections. Do not turn a runtime success into a
Claim conclusion. Every numerical or structural statement cites the relevant
Finding and source Artifact. Render Phase grouping only when Phases are present;
an ungrouped map is complete and valid.

Before an export, use `research_read` to read the current map and record any changed
Node or Claim status with `research_change`. Create a new report package per export;
verify its files, manifest, source revision, and Artifact references before
returning it. Read [report_template.md](references/report_template.md) for the
package layout and numerical discipline.
