# accepted_audit report residue fix plan

## Problem

After a supported `accepted_audit` has produced an accepted artifact,
`report_workspace` can still list `accepted_audit` in
`hypothesis_context.required_next_evidence`.

The root cause is report-side aggregation: required evidence is compared only
against evidence registry roles. `accepted_audit` is a workflow/audit phase and
accepted artifact state, not necessarily an evidence record role.

## Change Plan

1. Pass `manifest` into the hypothesis-context builder used by
   `report_workspace`.
2. Treat `accepted_audit` as satisfied when either:
   - `manifest.accepted_ts_refs` is non-empty, or
   - the active hypothesis has a `prediction_status` row with
     `phase=accepted_audit` and `claim_verdict=supported`.
3. Keep `pathway_audit` excluded from direct prediction aggregation; this fix
   must not reopen the previously fixed audit-contamination behavior.
4. Add regression tests for accepted artifact state and supported
   `accepted_audit` row state.
5. Sync the runtime skill and clear the TS workspace TODO after tests pass.
