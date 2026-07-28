# Decision Contract

A decision JSON is the only mutation instruction channel.

The public schema version remains `ts-decision`, but strict decisions require
the first node to submit a structured initial hypothesis, and all later
evidence-testing phases to reference an existing hypothesis.

Runtime decision shapes live under `templates/decision/`. Those files are the
authoritative examples for agent-facing workspace mutation. Test files are
regression fixtures only and must not be used as operating examples for live TS
research. Templates define JSON shape, provenance, evidence roles, and closure
semantics; they do not encode fixed retry classification or automatic branch
selection.

## Start `n000`

```json
{
  "schema_version": "ts-decision",
  "action": "start_node",
  "rationale": "Start endpoint validation and initial hypothesis generation.",
  "evidence_refs": [],
  "report_ref": {
    "report_id": "rep_20260622T010000",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "node_id": "n000",
    "phase": "endpoint",
    "hypothesis": "Initial endpoint-derived mechanism hypothesis.",
    "initial_mechanism_hypothesis": {
      "summary": "Concerted C-N formation on the singlet surface.",
      "derived_from": {},
      "structured_claim": {
        "reaction_center": {
          "forming_bonds": [{"atoms": [1, 2], "label": "C1-N2"}],
          "breaking_bonds": []
        },
        "reaction_class": ["bond_formation"],
        "elementary_step_model": "concerted",
        "electronic_model": {"surface": "ground_state"}
      },
      "testable_predictions": [],
      "required_evidence": ["initial_mechanism_hypothesis"],
      "uncertainties": [],
      "alternative_hypotheses": [],
      "evidence_refs": ["ev_hyp_0001"]
    },
    "expected_evidence": ["initial_mechanism_hypothesis"]
  }
}
```

`end_node n000` must close with endpoint facts. If supported, the
finalizer promotes `initial_mechanism_hypothesis` into
`mechanism_model.hypotheses[]`.

## Later Mechanism Nodes

```json
{
  "schema_version": "ts-decision",
  "action": "start_node",
  "rationale": "Open TS/Freq validation for the active hypothesis.",
  "evidence_refs": ["ev_candidate_001"],
  "report_ref": {
    "report_id": "rep_20260622T010500",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "parent_node": "n000",
    "phase": "tsfreq_validation",
    "hypothesis": "The candidate is a first-order saddle for hyp_0001.",
    "hypothesis_ref": {
      "hypothesis_id": "hyp_0001",
      "prediction_ids": ["pred_mode_001"]
    },
    "solution_ref": {
      "solution_id": "sol_scan_001",
      "strategy": "relaxed_scan_seed",
      "summary": "A constrained scan will seed this TS/Freq attempt."
    },
    "expected_evidence": ["gaussian_output", "imaginary_mode_summary"]
  }
}
```

`closure.mechanism.hypothesis_ref` must match the node's
`payload.hypothesis_ref`.
`payload.solution_ref` is optional lineage metadata for grouping alternative
search strategies under the same hypothesis. It must not be used as a verdict,
retry state, or automatic branch selector.
For `phase=pathway_audit`, `payload.pathway_ref` is mandatory and must name the
audited `pathway_id` and `step_id`. Before closing that node, register and cite
a `pathway_audit_summary` evidence record with
`quality.strict_pathway_decision=accepted` or
`quality.strict_pathway_decision=pathway_not_accepted`.

## Later Hypothesis Generation

A mechanism change is introduced before downstream testing with
`phase=hypothesis_generation`, a complete
`payload.initial_mechanism_hypothesis`, and
`payload.branch_context.relation=new_hypothesis_branch`. The node does not use
`payload.hypothesis_ref` because the new hypothesis does not exist in
`mechanism_model.json` until supported closure promotes it. The initial object
must declare its new `hypothesis_id`; use `parent_hypothesis_id` to identify the
hypothesis being changed. `phase=endpoint` is reserved for `n000`.

When the agent opens a same-hypothesis replacement solution, the new
`start_node` decision keeps the same `payload.hypothesis_ref`, supplies a new
`payload.solution_ref`, and records
`payload.branch_context.relation=new_solution_branch`. The new node's
`payload.parent_node` must equal `payload.branch_context.anchor_node`; the
failed or triggering node is recorded separately in
`payload.branch_context.from_node`. For same-hypothesis replacement solutions,
the anchor must equal the current hypothesis
`mechanism_model.hypotheses[].source_node`; an older global ancestor is an
overbroad anchor unless it is also that source node. The preflight validates
references, topology, and consistency; it does not decide whether the
replacement should be made.

For legacy lineage repair, use `action=update_workspace` with
`payload.repair_branch_anchor`:

```json
{
  "node_id": "n023",
  "new_anchor_node": "n020",
  "reason_code": "overbroad_anchor_node_for_new_solution_branch"
}
```

The repair is rejected for running nodes and for anchors that do not match the
node hypothesis `source_node`.

## Branch Relation Semantics

`branch_context.relation` records the intended graph relation between the new
node and existing workspace state. Pick from:

- `continue_parent` — same scientific object continues to the next evidence
  layer, or the same TS claim is re-validated with different protocol
  parameters. Requires `parent_node == branch_context.from_node`. A failed
  program attempt (e.g. IRC corrector convergence failure) that continues
  verifying the same TS claim is `continue_parent`, not a new branch; cite
  the failed attempt through `reason_code`, closure facts, and evidence with
  role `previous_attempt_summary`.
- `new_solution_branch` — same hypothesis, different candidate / search
  strategy (e.g. QST candidate failed → constrained scan candidate; strict
  connectivity refuted a TS/Freq-supported candidate → different TS-search
  method). Requires a new `solution_ref.solution_id` and
  `parent_node == branch_context.anchor_node == hypothesis.source_node`. Do
  not use for IRC-parameter changes, parser/scheduler follow-up, or next-layer
  validation.
- `new_hypothesis_branch` — the mechanism hypothesis changes (concerted →
  stepwise, ground-state → excited-state, ketone-side → ester-side treated
  as distinct hypotheses). Requires `phase=hypothesis_generation`.
- `new_pathway_branch` — pathway topology or step model changes while
  hypothesis handling stays explicit.
- `administrative_followup` — non-scientific control-plane work (monitoring
  handoff, report packaging, workspace repair, visualization). Must not
  carry a chemistry verdict.

## Closure Revision

```json
{
  "mechanism": {
    "summary": "The imaginary mode does not follow the reaction center.",
    "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_mode_001"]},
    "revision": {
      "action": "refute_prediction",
      "prediction_ids": ["pred_mode_001"],
      "changed_variable": "reaction_center"
    },
    "evidence_refs": ["ev_mode_002"]
  }
}
```

Allowed actions:

- `init_workspace`
- `start_node`
- `end_node`
- `update_workspace`
- `ask_user`
- `stop`

`start_node`, `end_node`, and `update_workspace` require a `report_ref`.
`report_workspace` should be run before the decision is written.
First-time `init_workspace` may bootstrap without a decision file, but
destructive force reinitialization must pass an `action=init_workspace`
decision so the reset is auditable.

The public `validate_decision --root <root> --decision-file <file>` preflight
validates both JSON shape and workspace-context requirements. Mutation commands
run the same validation internally before writing files and reject decision
files whose `action` does not match the invoked mutation command.

`update_workspace` may append evidence, knowledge, or provenance. It cannot
close a node, write a verdict, accept a TS, rewrite a pathway, or mutate
`mechanism_model.hypotheses[]`.

Machine authority is `ts_workspace/contracts/decision.schema.json`, the pure
Python decision validator, and the workspace-aware decision preflight used by
the public CLI.
