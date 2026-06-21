# Plan: Pathway Audit Outcome Semantics

## Problem

`pathway_audit` currently reuses the generic phase-level
`closure.claim_verdict` display and pathway finalization behavior. A supported
audit can therefore be read as pathway success, even when the audit evidence
actually says the strict pathway is not accepted.

The bug is semantic, not a branch-control problem. The workflow should not force
a follow-up branch. The agent should still decide whether to open a new
hypothesis branch, stop, or ask the user.

## Contract Change

- Keep `closure.claim_verdict` as phase-level judgment.
- Treat `pathway_audit` as an audit of pathway evidence, not as direct proof of
  the referenced step.
- Derive an audit outcome for display/reporting from structured audit evidence,
  closure reason codes, and closure text.
- Do not make `validate_workspace` require a new branch after a negative audit.
- Do not let a supported negative `pathway_audit` automatically mark a pathway
  step as `supported`.

## Implementation

1. Add a small pathway-audit outcome classifier in `ts_web.normalize`:
   - `pathway_not_accepted` when audit evidence/closure indicates
     `strict_pathway_supported=false`, `strict_pathway_decision=not_accepted`,
     missing connectivity, or no accepted TS.
   - `accepted_pathway` / existing pathway complete state only when the pathway
     model or manifest explicitly records accepted pathway state.
2. Use the classifier for:
   - node display label/tone/state for `pathway_audit`;
   - workspace `claim_state` when the latest closed node is a negative
     `pathway_audit` and there is no accepted TS/pathway.
3. Update finalizer semantics:
   - skip generic step-status mutation for `pathway_audit`;
   - reserve pathway model success for explicit accepted pathway artifacts/state.
4. Update docs to state the distinction between audit verdict and pathway
   verdict.
5. Add regression tests:
   - a supported negative `pathway_audit` displays as not accepted / amber;
   - validator still considers the workspace structurally valid;
   - the audit does not mark the referenced pathway step as supported.

## Validation

- Targeted `pytest` for workspace finalizer/validator and web normalization.
- Full test suite.
- `compileall`.
- `git diff --check`.
- Sync installed skill and repeat targeted/full validation there.
