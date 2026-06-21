# Plan: 2026-06-21 TODO Cleanup

## Scope

Resolve the four open workflow/UI TODOs recorded from the `trans1x_025`
run:

1. Fresh endpoint-based workspaces should use an explicit `n000` endpoint or
   preflight node.
2. `ts_web` mechanism analysis should expose chemistry evidence instead of
   terse closure summaries.
3. `ts_web` timeline should render decision-log events when no backtrack
   events exist.
4. Pathway status must not become supported before connectivity evidence
   passes.

## Constraints

- Keep existing historical workspaces valid.
- Do not change the public seven-command control plane.
- Keep all workspace mutations routed through decision JSONs.
- Do not make TS/Freq support imply pathway connectivity.

## Implementation Steps

1. Pathway semantics:
   - Change `ts_workspace.finalizers.node` so `tsfreq_validation` support does
     not set pathway step status to `supported`.
   - Let `connectivity_validation`, `accepted_audit`, and `pathway_audit`
     update pathway support.
   - Add tests for TS/Freq-only support and later connectivity support.

2. Fresh endpoint workflow:
   - Document the recommended explicit `n000` endpoint/preflight node in
     `SKILL.md` and workspace references.
   - Add a regression test proving explicit `node_id=n000` can be started and
     the following auto-numbered node becomes `n001`.
   - Preserve compatibility for workspaces without `n000`.

3. Web mechanism evidence:
   - Extend `ts_web.normalize` to aggregate mechanism facts and key evidence
     quality fields from `evidence_registry.json` and node closures.
   - Surface TS/Freq, IRC connectivity, mode, key-distance, and RMSD summaries
     through existing normalized explorer fields.

4. Web timeline:
   - Read `decision_log.jsonl` in `ts_web.normalize`.
   - Convert start/end/update decisions into normalized graph events.
   - Merge them with existing backtrack events without requiring frontend API
     changes.

5. Validation and release:
   - Run focused tests plus full test suite.
   - Sync authored checkout to `/home/iaw/TS/.agents/skills/transition-state-workflow`.
   - Verify the installed copy against the real `trans1x_025` workspace.
   - Clear completed TODO entries.
   - Commit and push to `origin/main`.
