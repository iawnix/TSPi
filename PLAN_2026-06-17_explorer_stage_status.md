# 2026-06-17 Explorer Stage-Status Plan

## Scope

This pass addresses two explorer contract issues recorded in
`/home/iaw/TS/.codex/TODO.md`:

1. resolved or superseded `backtrack_events[]` are stored but not drawn as
   historical graph edges;
2. node cards expose internal audit wording such as `completed; no TS claim`
   instead of a simple phase-level status.

No scientific claim, node closure rule, accepted-TS gate, or pathway gate should
be weakened. The internal v2 fields remain the source of truth for validation:
`lifecycle_state`, `run_state`, `claim_status`, `outcome`, `outcome_code`,
`claim_level`, `evidence_refs`, `pathway_id`, and `elementary_step_id`.

## Design

- Keep `state_contract.py` as the single owner for presentation vocabulary.
- Add a compact node-card presentation derived from existing internal fields:
  `Status[Phase]`, with phases limited to
  `Preflight`, `Endpoint`, `Candidate`, `Validation`, and `Pathway`.
- Keep raw `node_state`, `state_label`, `state_line`, `claim_status`, and
  `outcome` in the normalized payload for audit panels and tests.
- Make the explorer card and selected-node header use the compact card label.
  The Summary tab should still show both the compact display label and the raw
  audit fields.
- Emit backtrack graph edges for all canonical backtrack event states. Active
  events remain the only events that affect planning; resolved and superseded
  edges are historical rendering.

## Mapping Rules

- `not_started` -> `Ready[Phase]`
- `pending`, `running`, `parsing` -> `Running[Phase]`
- `completed` with successful claim/outcome -> `Success[Phase]`
- `completed` with `not_evaluated/none` -> `Success[Phase]`
- failure outcomes, parser failures, numerical failures, rejected claims, or
  ambiguous claims -> `Error[Phase]`
- administrative stop -> `Stopped[Phase]`

The details pane remains the place for the precise reason, such as
`gaussian_zsymb_eof_qst2_input_format`, `wrong_mode`, or `tsfreq_validated`.

## Validation

- Unit tests for the compact card label mapping.
- Normalizer tests showing endpoint evidence nodes display `Success[Endpoint]`
  rather than `completed; no TS claim`.
- Backtrack tests showing resolved/superseded events still emit historical
  `kind=backtrack` edges with `event_state`.
- Smoke normalize the live `trans1x_080` workspace and check:
  - n020/n030/n035/n036 show `Success[Endpoint]`;
  - n050 shows `Error[Candidate]` with its diagnostic still present in
    `state_line`;
  - the resolved n050 -> n040 backtrack edge exists.
- Sync to `/home/iaw/.codex/skills/transition-state-workflow`, re-run targeted
  validation there, then mark the TODO entries complete.
