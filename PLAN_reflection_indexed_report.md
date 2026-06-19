# Plan: structured reflection and indexed report

## Problem

The root ledgers already hold durable workspace state, and `end_node` updates
those ledgers through the control-plane writer. `report_workspace` should not
duplicate the whole tree as a bulky JSON payload. It should point the model to
the durable records that matter, especially `reflection.md` files.

`reflection.md` is also too free-form today: `end_node` receives structured
program and mechanism facts for `closure_explanation`, but the rendered
reflection only uses summary text plus one knowledge-update line. That loses
the explicit evidence/source trail in the most important per-node reasoning
artifact.

Finally, `pathway_model.json` is created by `init_workspace` but a multi-step
pathway definition has no public initialization path after retiring
`pathway-init`.

## Contract

- `init_workspace` can initialize `pathway_model.json` directly:
  `--pathway-mode`, `--pathway-id`, `--pathway-label`, and repeatable
  `--pathway-step step_id:from->to`.
- `reflection.md` is rendered from structured closure fields:
  program facts, mechanism facts, evidence/source refs, knowledge update, open
  questions, and next branch.
- `report_workspace` defaults to an index-style payload:
  current phase, focus, claim readiness, context item paths, ledger references,
  and a compact node index. It should not inline every node closure payload.
- Full node closure details remain available in `node.json` and
  `nodes/<node>/reflection.md`; the report points to those files.

## Implementation Steps

1. Extend `init_workspace` CLI and workspace initializer to write pathway
   definitions into `pathway_model.json`.
2. Extend `ReflectionSpec` and `write_reflection()` to render structured facts
   with `evidence_ref` and `source_path` where available.
3. Replace public `report_workspace.nodes` with a compact `node_index` and
   `ledger_refs`, while keeping `situation.context_items` as the ranked
   retrieval list.
4. Update docs and tests so the public contract reflects ledger-first,
   reflection-centered context.
5. Validate authored and installed skill trees plus a real workspace smoke.
