# Context-Aware Decision Validation Plan

## Problem

`validate_decision` currently validates the decision JSON shape but does not
check whether a `start_node` mutation would violate workspace-level replacement
backtrack provenance. A replacement branch can therefore pass preflight, be
written by `start_node`, and only fail later in `validate_workspace` with
`missing_replacement_backtrack_event`.

## Plan

1. Keep the existing pure JSON validator as the schema-level contract.
2. Add a workspace-aware decision validator for mutation preflight.
3. For `start_node`, detect when the previous terminal node is unresolved
   (`refuted`, `inconclusive`, or `not_evaluated`) and the proposed node is not
   a descendant of it.
4. Require `payload.backtrack` in that replacement scenario, and require its
   `from_node` to point to the terminal unresolved node.
5. Use the workspace-aware validator in both the CLI `validate_decision` command
   and `engine.start_node`, so the mutation cannot bypass preflight.
6. Add regression tests for CLI preflight and direct `start_node` fail-fast
   behavior, while preserving workspace validator coverage for legacy/corrupt
   ledgers.

## Validation

- Targeted tests for workspace validator and CLI.
- Full pytest suite if targeted tests pass.
- `compileall` and `git diff --check`.
