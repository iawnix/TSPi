# Plan: Public Replacement Backtrack And Explorer Edge

## Problem

`trans1x_015` exposed two related gaps in the backtrack contract.

1. The public `ts_workspace.py start_node` command cannot pass replacement
   backtrack fields, even though the lower-level workspace writer already
   supports `replaces_node` and canonical `backtrack_events[]` creation.
2. The explorer shows the canonical rollback edge from failed node to ancestor,
   but it does not visibly show the replacement branch produced from
   `new_branch_node`.

## Scope

- Keep `tree.json.backtrack_events[]` as the canonical source of truth.
- Expose replacement-branch intent through the public `start_node` command and
  `validate_decision` schema.
- Let explorer payloads include a derived, display-only edge from
  `from_node` to `new_branch_node` when a backtrack event has a replacement
  branch.
- Do not change accepted-TS evidence gates or chemistry decision policy.

## Implementation Steps

1. Add public `start_node` CLI flags:
   - `--replaces-node`
   - `--backtrack-reason-code`
   - `--backtrack-reason`
   - `--backtrack-evidence-ref`
   - `--supersede-active-backtrack`
2. Pass those fields through `start_node_from_cli_args()` into the existing
   `create_ts_branch_decision_artifacts_from_cli_args()` bridge.
3. Extend `validate_decision` public shape for `start_node` to accept the same
   fields and reject malformed types before mutation.
4. Extend normalizer output with `kind=backtrack_replacement` derived edges:
   - source: `from_node`
   - target: `new_branch_node`
   - metadata: event id, `to_node`, `event_state`, `reason_code`, reason
5. Update explorer CSS/edge labeling only as needed so the new kind renders as
   a dashed backtrack-family edge.
6. Add regression tests for:
   - public CLI creates canonical replacement backtrack event;
   - public decision validator accepts replacement fields;
   - normalizer emits both canonical rollback and replacement display edge.
7. Validate with targeted tests, full tests as practical, and real
   `trans1x_015` workspace normalization/validation.
8. Sync installed skill, verify parity, commit, push, then clear the two
   unresolved TODO entries from `/home/iaw/TS/.codex/TODO.md`.

