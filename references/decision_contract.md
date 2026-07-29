# Decision Contract

A decision JSON is the only mutation instruction channel.

The public schema version remains `ts-decision`. Strict decisions use `n000`
only for endpoint validation, register a mechanism hypothesis through a
separate `propose_hypothesis` mutation, and require all later evidence-testing
nodes to reference a registered hypothesis.

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
  "rationale": "Start endpoint validation.",
  "evidence_refs": [],
  "report_ref": {
    "report_id": "rep_20260622T010000",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "node_id": "n000",
    "phase": "endpoint",
    "hypothesis": "The supplied structures define usable endpoint basins.",
    "expected_evidence": [
      "endpoint_provenance",
      "charge_multiplicity",
      "atom_mapping",
      "reaction_center_delta"
    ]
  }
}
```

`end_node n000` closes only the endpoint claim. It does not create or promote a
mechanism hypothesis.

## Propose A Hypothesis

After `n000` is supported and its evidence is registered, create the initial
hypothesis without creating a node:

```json
{
  "schema_version": "ts-decision",
  "action": "propose_hypothesis",
  "rationale": "Propose an endpoint-derived mechanism hypothesis.",
  "evidence_refs": ["ev_endpoint_0001"],
  "report_ref": {
    "report_id": "rep_20260622T010500",
    "workspace_root": "tssearch_example"
  },
  "payload": {
    "proposed_hypothesis": {
      "hypothesis_id": "hyp_0001",
      "summary": "Concerted C-N formation on the singlet surface.",
      "derived_from": {},
      "structured_claim": {
        "reaction_center": {"forming_bonds": [], "breaking_bonds": []},
        "reaction_class": ["bond_formation"],
        "elementary_step_model": "concerted",
        "electronic_model": {"surface": "ground_state"}
      },
      "mechanism_claims": [],
      "testable_predictions": [],
      "required_evidence": [],
      "uncertainties": ["Endpoint geometry does not prove reaction timing."],
      "alternative_hypotheses": [],
      "evidence_refs": ["ev_endpoint_0001"]
    },
    "proposal_context": {
      "kind": "initial",
      "from_node": "n000",
      "anchor_node": "n000",
      "changed_variable": "initial_mechanism_model",
      "reason_code": "endpoint_interpretation",
      "evidence_refs": ["ev_endpoint_0001"]
    }
  }
}
```

The mutation writes a `status=proposed` entry with `source_node`,
`branch_anchor_node`, `proposed_by_decision`, and `proposal_context`. It has no
`claim_verdict` and does not add an entry to `research_state.json`. The first
evidence-producing node that references it changes the status to `active`.
Use `templates/decision/propose_initial_hypothesis.json` for the complete
runtime shape.

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
    "branch_context": {
      "relation": "continue_parent",
      "from_node": "n000",
      "anchor_node": "n000"
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

## Alternative Hypothesis Proposal

Use `action=propose_hypothesis` with `proposal_context.kind=alternative` and a
new `proposed_hypothesis.hypothesis_id`. The hypothesis must include
`parent_hypothesis_id`, and the proposal must cite already registered evidence.
`proposal_context.from_node` identifies the evidence-producing trigger;
`proposal_context.anchor_node` becomes the new hypothesis
`branch_anchor_node`.

The first evidence node for that proposal uses
`branch_context.relation=new_hypothesis_branch`, references the proposed
`hypothesis_id`, and exactly matches the stored `from_node`, `anchor_node`,
`changed_variable`, and `reason_code`. This node activates the hypothesis. See
`templates/decision/propose_alternative_hypothesis.json`.

When the agent opens a same-hypothesis replacement solution, the new
`start_node` decision keeps the same `payload.hypothesis_ref`, supplies a new
`payload.solution_ref`, and records
`payload.branch_context.relation=new_solution_branch`. The new node's
`payload.parent_node` must equal `payload.branch_context.anchor_node`; the
failed or triggering node is recorded separately in
`payload.branch_context.from_node`. For same-hypothesis replacement solutions,
the agent selects an existing checkpoint after inspecting its node context.
The anchor must be an ancestor of `from_node`; it need not equal the hypothesis
proposal source. The preflight validates references, topology, and consistency;
it does not choose the checkpoint or decide whether replacement should occur.

For legacy lineage repair, use `action=update_workspace` with
`payload.repair_branch_anchor`:

```json
{
  "node_id": "n023",
  "new_anchor_node": "n020",
  "reason_code": "repair_branch_checkpoint"
}
```

The repair is rejected for running nodes and for anchors that are not ancestors
of the recorded `branch_context.from_node`.

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
  `parent_node == branch_context.anchor_node`; the selected anchor must be an
  ancestor of `branch_context.from_node`. Do
  not use for IRC-parameter changes, parser/scheduler follow-up, or next-layer
  validation.
- `new_hypothesis_branch` — the first evidence node for an alternative
  `status=proposed` hypothesis. It must match that hypothesis's stored
  `proposal_context`; later nodes under the same hypothesis use another
  scientifically appropriate relation.
- `new_pathway_branch` — pathway topology or step model changes while
  hypothesis handling stays explicit.

Monitoring, report packaging, snapshots, workspace repair, and visualization
do not create nodes. Historical `administrative_followup` records remain
read-compatible only.

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
- `propose_hypothesis`
- `end_node`
- `update_workspace`
- `ask_user`
- `stop`

`start_node`, `propose_hypothesis`, `end_node`, and `update_workspace` require a
`report_ref`.
`report_workspace` should be run before the decision is written.
First-time `init_workspace` may bootstrap without a decision file, but
destructive force reinitialization must pass an `action=init_workspace`
decision so the reset is auditable.

The public `validate_decision --root <root> --decision-file <file>` preflight
validates both JSON shape and workspace-context requirements. Mutation commands
run the same validation internally before writing files and reject decision
files whose `action` does not match the invoked mutation command.

`update_workspace` may append evidence or provenance and may apply an explicit
lineage repair. It cannot
close a node, write a verdict, accept a TS, rewrite a pathway, or mutate
`hypotheses.json.hypotheses[]`.

Machine authority is `ts_workspace/contracts/decision.schema.json`, the pure
Python decision validator, and the workspace-aware decision preflight used by
the public CLI.
