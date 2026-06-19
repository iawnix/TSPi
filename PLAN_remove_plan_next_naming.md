# Plan: remove old plan_next naming

## Problem

The public `report_workspace` contract now behaves as a read-only workspace
context and claim-readiness report, but the implementation still lives under
`src/transition_state_workflow/core/plan_next` in the older tree and exposed
planner-shaped names and fields.

That naming keeps the old planner responsibility visible in the codebase even
after the report contract stopped choosing the model's next route or command.

## Contract

- The report-context implementation should live under
  `core/workspace_report`.
- Function and class names should use `workspace_report` or `attention` terms,
  not `plan_next` or planner terms.
- Public CLI behavior stays unchanged: users still call
  `ts_workspace.py report_workspace`.
- No compatibility import path for `core.plan_next` should remain.
- Raw report packets should expose `focus` and `decision_authority`, not
  `planning_focus`, `planner_role`, or `PLAN_SCHEMA`.

## Implementation Steps

1. Rename the package directory from `core/plan_next` to
   `core/workspace_report`.
2. Rename exported packet/snapshot functions and classes.
3. Rename internal phase/focus helpers from planner language to attention/report
   language.
4. Update callers, package exports, tests, and docs.
5. Validate authored and installed trees plus a real workspace smoke.
