# Chemistry Hypothesis Workspace

Load this when a TS search is exploratory, failed, ambiguous, or likely to need
multiple methods. The workspace is a chemistry hypothesis notebook with
machine-readable evidence, not just a directory of calculations.

## Principle

Tool choice must follow the current chemical hypothesis.

Do not start with "run NEB" or "run Gaussian" as the primary plan. Start with:

- what reaction class is plausible;
- what charge and multiplicity imply;
- which bonds, angles, fragments, spins, and charges should change;
- what evidence would support or refute each candidate mechanism;
- which computation is the lowest-cost test of the next hypothesis.

The workflow is:

```text
mechanism hypothesis -> tool choice -> evidence gate -> knowledge update -> next hypothesis
```

## Required Workspace Additions

In addition to `manifest.json`, `tree.json`, and `nodes/`, exploratory tasks
should keep:

```text
tssearch_<system>/
├── mechanism_model.json
├── knowledge_base.md
├── evidence_registry.json
└── nodes/
    └── nNNN_label/
        ├── hypothesis.md
        ├── decision_card.md
        └── reflection.md
```

Use `scripts/ts_hypothesis_workspace.py init` to create these files.

## `mechanism_model.json`

This is the current best chemical model. It evolves as evidence arrives.

Required fields:

```json
{
  "schema": "tssearch-mechanism-model-v1",
  "system": "example",
  "charge": 0,
  "multiplicity": 1,
  "reaction_class": "unknown",
  "reaction_class_confidence": "low",
  "key_atoms": [],
  "expected_bond_changes": [],
  "expected_angle_changes": [],
  "electronic_hypotheses": [],
  "analysis_plan": {
    "reaction_type": [],
    "reaction_center": [],
    "electronic": [],
    "orbital": [],
    "energy": []
  },
  "mechanism_analysis": {
    "reaction_type": [],
    "reaction_center": [],
    "electronic": [],
    "orbital": [],
    "energy": []
  },
  "validated_facts": [],
  "refuted_hypotheses": [],
  "open_questions": [],
  "tool_implications": [],
  "updated_at": "2026-06-05T00:00:00+08:00"
}
```

Rules:

- `reaction_class` is a hypothesis until evidence supports it.
- `validated_facts` must cite evidence IDs or files.
- `refuted_hypotheses` must cite the node or evidence that refuted them.
- `open_questions` should drive the next branch.
- Do not erase wrong hypotheses; move them to `refuted_hypotheses`.
- `analysis_plan` belongs to the chemical hypothesis. Use it for expected
  reaction type, reaction-center checks, electronic/spin/charge diagnostics,
  orbital/population follow-up, and energy checks that still need evidence.
- `mechanism_analysis` is structured evidence, not prose decoration. Record each
  available layer as `supported`, `refuted`, `ambiguous`, or `unavailable` with
  evidence references or a `source` path to the direct output/parsed descriptor:
  - `reaction_type`: proton transfer, HAT, PCET, rearrangement, substitution,
    atom transfer, dissociation, spin crossover, or another explicit class.
  - `reaction_center`: mapped atoms, forming/breaking bonds, angles, fragments,
    and mode participation.
  - `electronic`: charge, multiplicity, `<S^2>`, spin density, donor/acceptor
    charge migration, and state consistency.
  - `orbital`: frontier orbitals, occupation, population/NBO-style descriptors,
    or a clear unavailable record when the output lacks those sections.
  - `energy`: endpoint energies, TS energy, rough or validated barrier, reaction
    energy, and whether the barrier shape is chemically plausible.

## `evidence_registry.json`

This file indexes all decision-relevant evidence, including failed runs.

Evidence records should distinguish:

- `raw_output`: Gaussian `.out`, xTB log, NEB trajectory, IRC output.
- `parsed_summary`: parser output or extracted metrics.
- `structure`: XYZ, Gaussian final geometry, displaced endpoint.
- `connectivity_check`: RMSD and reaction-center bond/angle comparison.
- `mechanistic_observation`: spin density, `<S^2>`, charge/bond-order proxy.
- `mechanism_analysis`: structured reaction type, electronic, orbital, or energy
  observation linked to the current mechanism model.
- `decision_card`: why a branch was chosen.
- `reflection`: what a failed or ambiguous branch changed chemically.

Minimum record:

```json
{
  "evidence_id": "ev_001",
  "kind": "parsed_summary",
  "path": "/abs/path/summary.json",
  "node_id": "n230_gaussian_tsfreq",
  "claim": "Exactly one imaginary frequency was parsed.",
  "evidence_state": "supports",
  "created_at": "2026-06-05T00:00:00+08:00"
}
```

## Knowledge Base

`knowledge_base.md` is the human-readable running synthesis. Keep it short and
source-backed:

```markdown
## Current Mechanism Model

## Validated Facts

## Refuted Hypotheses

## Open Questions

## Next Chemical Decision
```

Only promote facts from parsed evidence or explicit structural checks. Do not
promote visual impressions unless they are recorded as weak observations.

## Decision Cards

Every new branch should have `decision_card.md` before execution:

```markdown
## Chemical Hypothesis
What this branch is testing.

## Why This Tool
Why NEB, scan, QST, dimer, QBICS dMECP, Gaussian TS/Freq, displacement, or IRC
is the right test now.

## Expected Supporting Evidence
What result would support the hypothesis.

## Refutation Criteria
What result would close or backtrack this branch.

## Cost And Risk
Compute cost, numerical risk, and chemical risk.

## Next If Supported
The next validation layer.

## Next If Refuted
The ancestor or alternative hypothesis to branch from.
```

Use `scripts/ts_hypothesis_workspace.py decision-card` to create a template.

## Multi-Step Pathway Layer

Use `pathway_model.json` only when a mechanism has multiple elementary TS
claims, such as reactant -> intermediate -> product. This layer aggregates
accepted elementary steps; it does not change the node-level evidence gates.

Create the pathway before opening step-scoped branches:

```bash
python scripts/ts_hypothesis_workspace.py pathway-init \
  --root tssearch_<system> \
  --mode multi_step \
  --pathway-id p001 \
  --label "R to P through I" \
  --step s1:R->I \
  --step s2:I->P
```

Every node that belongs to one elementary step should carry the step metadata:

```bash
python scripts/ts_hypothesis_workspace.py decision-card \
  --root tssearch_<system> \
  --node-id n020_s1_endpoint_gate \
  --stage endpoint_minima_validation \
  --hypothesis "Validate endpoint references for step s1." \
  --operation gaussian-endpoint-validation \
  --pathway-id p001 \
  --step-id s1
```

When an elementary step is accepted, finalize that node with the same pathway
metadata:

```bash
python scripts/ts_hypothesis_workspace.py finalize-node \
  --root tssearch_<system> \
  --node-id n080_s1_connectivity \
  --claim-status accepted_ts \
  --decision accept_pathway_step_ts \
  --summary "Step s1 has TS/Freq plus connectivity evidence." \
  --primary-file nodes/n080_s1_connectivity/parsed/connectivity.json \
  --pathway-id p001 \
  --step-id s1 \
  --evidence '<tsfreq evidence json>' \
  --evidence '<connectivity evidence json>' \
  --computational-outcome "TS/Freq and connectivity passed for step s1." \
  --mechanistic-implication "Only elementary step s1 is accepted." \
  --next-branch "Continue to the next incomplete pathway step."
```

Rules:

- `accepted_ts` is one elementary-step claim. The whole pathway is `complete`
  only when every required step in `pathway_model.json` is bound to its own
  accepted TS node.
- Do not bind the same accepted TS node to multiple pathway steps. If a
  frequency-validated saddle might describe a different step, keep the old node
  historical and create a new step-scoped node with `--input-ref` plus new
  endpoint/connectivity evidence.
- `plan-next` scopes endpoint, candidate, TS/Freq, and connectivity gates to
  the next incomplete pathway step. A previous step's accepted TS may be the
  tree parent for the next endpoint branch, but it is not evidence for the next
  step's TS claim.
- If a branch merely fails numerically or tests one bad local route, keep that
  failure branch-local. If evidence refutes or leaves ambiguous the elementary
  step itself, finalize the node with `--pathway-step-status rejected` or
  `--pathway-step-status ambiguous`; the whole pathway then stops normal
  forward planning until the mechanism hypothesis is reassessed.
- `ts_normalize_view.py` emits pathway and node step metadata, and
  `ts_validate_workspace.py` rejects duplicate accepted-node bindings or
  inconsistent node/step metadata.

## Planning Packet

Use `scripts/ts_hypothesis_workspace.py plan-next` when an agent needs compact
state context before deciding the next chemical branch:

```bash
python scripts/ts_hypothesis_workspace.py plan-next \
  --root tssearch_<system> \
  --pretty
```

After an accepted TS exists, `plan-next` defaults to audit/archive context. To
ask for a chemically distinct alternative mechanism, make that intent explicit:

```bash
python scripts/ts_hypothesis_workspace.py plan-next \
  --root tssearch_<system> \
  --alternative-mechanism \
  --pretty
```

This mode keeps the accepted TS visible as prior evidence, but suggested
decision cards start from a new mechanism preflight instead of overwriting or
reusing the accepted branch as proof.

`plan-next` is read-only by default. It summarizes:

- validator errors that block promotion;
- active frontier and prepared nodes;
- `planning_focus`, which chooses the node or mode that should guide the next
  model call;
- `context_policy` and prioritized `context_items`, which act as the structured
  context-management layer for the next model call;
- retrieval ranks on `context_items`, so the next agent call knows which
  workspace artifacts to read first;
- missing gates such as `endpoint_minima_missing`, `candidate_missing`,
  `tsfreq_validation_missing`, or `connectivity_missing`;
- allowed and forbidden next action classes;
- validated facts, refuted hypotheses, and open questions from
  `mechanism_model.json`;
- canonical `backtrack_events[]` plus suggested `record-backtrack` actions when
  failed or ambiguous branches lack a backtrack decision;
- failed or ambiguous branch reflections;
- suggested decision-card drafts for the next evidence layer.

`planning_focus` and `context_items` are planning-packet fields, not workspace
state. Do not copy them into `tree.json`. They are regenerated from
`tree.json`, node records, reflections, evidence, and the mechanism model each
time `plan-next` runs.

Backtrack-aware planning has two hard rules:

- `planning_focus.mode=backtrack_decision_needed` means a failed or ambiguous
  node has no canonical backtrack event yet. Do not open a child under that
  failed node; first run `record-backtrack` and choose the closest chemically
  meaningful ancestor.
- `planning_focus.mode=backtrack_replan` means an active backtrack event exists.
  New decision cards should use `planning_focus.parent_for_new_branch`, which
  is the event's `to_node`, as the tree parent. If artifacts from the failed
  node are useful, reference them through `input_refs`, not by making the failed
  node the primary parent.

Only one `event_state=active` backtrack is allowed in a workspace. If another
backtrack should become the current planning target, use `update-backtrack` to
mark the existing active event `resolved` or `superseded`, or run
`record-backtrack` with `--supersede-active` so the old active event is retired
before the new one is written.

When a backtrack target is active, `search_state.global_phase` records the
highest workspace-wide evidence layer, while `search_state.phase` is the
focus-local next gate at the backtrack target. This lets the agent revisit an
earlier chemical decision without losing the validated evidence elsewhere in the
tree.

## Mechanism Reinterpretation And Evidence Reuse

A rejected or ambiguous TS/Freq node can be chemically useful without becoming
accepted under its original hypothesis. For example, a wrong-mode TS may fit a
newly recognized intermediate-to-product step rather than the original
reactant-to-product boundary.

The rule is:

- keep the original failed node closed as `rejected` or `ambiguous`;
- create a new decision-card node for the reframed intended reaction boundary;
- set `--input-ref <old_tsfreq_node>` on the new node if the old TS/Freq
  evidence is being reused;
- attach new endpoint or intermediate references to the new node;
- attach new connectivity evidence to the new node;
- finalize only the new node as `accepted_ts`, and only if that node has both
  recognized TS/Freq evidence and recognized connectivity evidence.

`plan-next` reports these cases under `reframe_candidates` and may suggest
`reframe_validated_wrong_mode_tsfreq_with_new_endpoint_refs`. This is a prompt
to design a new mechanism-boundary test, not permission to edit or promote the
old rejected node.

It does not choose the chemistry for the agent. The agent must still decide the
specific mechanism hypothesis, route, observables, and compute cost. To
materialize suggested decision-card nodes, use the explicit write mode:

```bash
python scripts/ts_hypothesis_workspace.py plan-next \
  --root tssearch_<system> \
  --write-decision-cards \
  --pretty
```

Run the validator after writing suggested cards and before launching compute.

## Node Start

Use `scripts/ts_hypothesis_workspace.py start-node` as soon as a branch begins
execution:

```bash
python scripts/ts_hypothesis_workspace.py start-node \
  --root tssearch_<system> \
  --node-id n020_gaussian_endpoint_opt \
  --run-state running \
  --decision start_remote_gaussian \
  --summary "Gaussian endpoint optimization is running on compute-0-30." \
  --primary-file nodes/n020_gaussian_endpoint_opt/scripts/run_endpoint_opt.sh
```

This is the supported way to add a node to `active_frontier` and append a
`start_node` event. It does not create a scientific claim.

## Node Finalization

Use `scripts/ts_hypothesis_workspace.py finalize-node` whenever a branch has a
post-execution state, including candidate-only, validated, rejected, ambiguous,
stopped, or accepted outcomes.

`finalize-node` is the closure path for:

- `node.json` lifecycle, run, claim, outcome, display, and evidence pointers;
- `tree.json` active, closed, accepted, and event indexes;
- `evidence_registry.json` records for parsed outputs, structures, logs, or
  connectivity checks;
- `reflection.md` computational outcome, mechanistic implication, knowledge
  update, and next branch;
- optional `knowledge_base.md` and `mechanism_model.json` updates;
- `manifest.json` only when an accepted TS changes workspace-global state.

Do not manually update those files as separate steps after execution. If a
completed node needs a state change, run `finalize-node` again with a new
evidence record and reflection text so the workspace remains auditable.

Endpoint optimization nodes that validate reactant/product minima should use
`claim_status=endpoint_minima_ready`; `finalize-node` derives
`outcome=endpoint_minima_validated` and the claim level automatically. Reserve
`endpoint_connected` for TS connectivity screens that compare displacement or
IRC endpoints to intended references.

## Backtracking

Use `scripts/ts_hypothesis_workspace.py record-backtrack` whenever a failed or
ambiguous branch sends the search back to an earlier chemistry decision:

```bash
python scripts/ts_hypothesis_workspace.py record-backtrack \
  --root tssearch_<system> \
  --from-node n030_gaussian_qst2 \
  --to-node n020_gaussian_endpoint_opt \
  --reason-code qst2_internal_coordinate_failure \
  --reason "Gaussian QST2 failed during redundant-internal setup; return to validated endpoints and try Cartesian QST2 or NEB."
```

By default, `record-backtrack` refuses to write a second active backtrack event.
Use `--event-state resolved` or `--event-state superseded` for historical
records, or pass `--supersede-active` when a new active backtrack should replace
the previous active one.

`--reason-code` is a free-form diagnostic label for the graph edge, like
`outcome_code` on `node.json`. It is not the canonical node `outcome`. Close the
failed node separately with `finalize-node` using a valid state pair such as
`claim_status=not_evaluated, outcome=numerical_failure,
outcome_code=qst2_internal_coordinate_failure`.

Leave `--new-branch-node` empty unless that new branch should be marked as part
of the backtrack event. Most views should mark the failed branch, not the new
candidate branch.

After recording the backtrack, rerun `plan-next`. If the event remains
`event_state=active`, the planning packet should route the next branch to the
event's `to_node`. Use `update-backtrack` to mark the event `resolved` or
`superseded` only when it should remain historical context rather than the
current branch-routing decision:

```bash
python scripts/ts_hypothesis_workspace.py update-backtrack \
  --root tssearch_<system> \
  --backtrack-id bt_n030_gaussian_qst2_to_n020_gaussian_endpoint_opt_qst2_internal_coordinate_failure \
  --event-state resolved \
  --reason "A replacement branch has been created from the endpoint gate."
```

`update-backtrack --event-state active` also follows the single-active rule. If
another active backtrack exists, pass `--supersede-active` only when the updated
event should become the current planning target and the old active event should
be retired.

## Chemistry-Driven Tool Selection

- Use scan when one dominant coordinate is chemically plausible and cheap to
  test, such as simple proton transfer or bond stretch.
- Use NEB when optimized reactant/product minima are distinct and atom mapping
  gives a meaningful continuous path.
- Use QST2/QST3 when optimized endpoints and a chemically reasonable guess are
  available at the Gaussian validation level.
- Use dimer when a local saddle is plausible but endpoint identity or mapping is
  uncertain.
- Use QBICS dMECP when diabatic fragment states are chemically natural for an
  atom-transfer or bond-switching hypothesis.
- Use imaginary-mode displacement plus endpoint optimization as the first
  connectivity screen when cheaper than IRC.
- Use IRC when displacement/endpoints remain ambiguous or publication-grade
  connectivity proof is required.

## Evidence Gates

Candidates can move forward only through gates:

```text
mechanism_preflight
-> endpoint_minima_ready
-> candidate_plausible
-> tsfreq_validated
-> mode_matches_hypothesis
-> endpoint_connected or irc_connected
-> accepted_ts
```

Failure at a gate should be closed with `finalize-node`, including the evidence
record, reflection, and any source-backed updates to `mechanism_model.json` and
`knowledge_base.md`.

## Reflection As Knowledge Update

After any failed or ambiguous branch, decide which canonical `outcome` applies
and put the program-specific or chemistry-specific label in `outcome_code`:

- numerical: `outcome=numerical_failure`; fix route, convergence, grid, memory,
  environment, or initial guess;
- structural: `outcome=wrong_endpoint` or `outcome=wrong_mode`; candidate
  collapsed to an endpoint, conformer, or wrong mode;
- mechanistic: `outcome=chemical_failure`, `outcome=wrong_endpoint`, or
  `outcome=wrong_mode`; wrong reaction class, charge/multiplicity, spin state,
  product reference, or non-distinct endpoint;
- evidence-limited: `outcome=parser_refused` or an `ambiguous` branch with the
  most specific allowed outcome; needs cheaper connectivity screen or IRC.

Then record:

- validated facts learned;
- hypotheses refuted;
- open questions created;
- the next branch and its chemical difference from the failed branch.

Write those records through `finalize-node`; `decision_card.md` and
`hypothesis.md` remain pre-execution records and should not be rewritten into
post-execution conclusions.
