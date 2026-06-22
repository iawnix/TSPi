# Pathway Audit Report Fix Plan

## Problem

`report_workspace` counted every `prediction_status` row by
`claim_verdict`. For `pathway_audit`, `claim_verdict=supported` supports the
audit conclusion, not the audited prediction itself. A negative audit could
therefore make one connectivity prediction appear in both
`supported_predictions` and `refuted_predictions`.

## Fix Scope

- Exclude `pathway_audit` rows from direct prediction verdict aggregation.
- Expose pathway audit outcomes separately under `hypothesis_context`.
- Mark negative audits with `recommended_next_action=start_new_branch`.
- Document that strict R->P / mandatory IRC tasks must not stop at a negative
  audit unless the user explicitly stops or no meaningful branch remains.

## Validation

- Add a regression test where a refuted connectivity prediction is audited by a
  supported negative `pathway_audit`.
- Run targeted report, web, report-builder, and workspace validator tests.
- Re-run `report_workspace` on the trans1x_025 workspace and verify the
  audited connectivity prediction is no longer simultaneously supported and
  refuted.
