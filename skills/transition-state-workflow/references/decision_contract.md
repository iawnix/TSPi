# Decision Contract

New mutations use `ts-decision/2`. A decision is selected by the Root Agent,
validated against the live workspace, and applied transactionally.

Required mutation provenance:

- unique `decision_id`
- `report_ref.report_id` and `report_ref.workspace_root`
- current `base_revision`
- explicit rationale and evidence refs
- one bounded payload

Pi constructs this envelope with `ts_workspace_decision_draft`, validates it with
`ts_workspace_decision_validate`, and applies it with `ts_workspace_decision_apply`.
The report ID is derived from the current workspace revision. Apply verifies both
the resolved workspace root and that derived ID, then repeats the complete dry
run under the workspace lock. Validate is a preview and cannot be reused as an
authorization or validation token.

## Start Intake

`n000` is the only intake node and has no parent or branch context.

```json
{
  "schema_version": "ts-decision/2",
  "decision_id": "dec_intake_start",
  "action": "start_node",
  "rationale": "Normalize the supplied structures and research constraints.",
  "evidence_refs": [],
  "report_ref": {"report_id": "rep_...", "workspace_root": "/path/to/workspace"},
  "base_revision": "sha256:...",
  "payload": {
    "node_id": "n000",
    "parent_node": null,
    "node_type": "intake",
    "objective": "Normalize user inputs, structures, constraints, and completion criteria."
  }
}
```

Close intake with `closure.intake.status=ready|needs_input` and
`closure.program.outcome=not_run` unless a real program ran.

## Propose A Hypothesis Node

Hypothesis creation is a mechanism node, not a root-level mutation.

```json
{
  "schema_version": "ts-decision/2",
  "decision_id": "dec_mechanism_start",
  "action": "start_node",
  "rationale": "Create a falsifiable endpoint-derived mechanism model.",
  "evidence_refs": ["ev_intake_001"],
  "report_ref": {"report_id": "rep_...", "workspace_root": "/path/to/workspace"},
  "base_revision": "sha256:...",
  "payload": {
    "node_id": "n001",
    "parent_node": "n000",
    "node_type": "mechanism",
    "objective": "Propose a falsifiable mechanism.",
    "mechanism_action": "propose",
    "proposed_hypothesis": {
      "hypothesis_id": "hyp_0001",
      "parent_hypothesis_id": null,
      "summary": "Concerted bond formation on the singlet surface.",
      "derived_from": {},
      "structured_claim": {
        "reaction_center": {"forming_bonds": [], "breaking_bonds": []},
        "reaction_class": ["bond_formation"],
        "elementary_step_model": "concerted",
        "electronic_model": {"spin_surface": "singlet"}
      },
      "mechanism_claims": [],
      "testable_predictions": [
        {
          "prediction_id": "pred_mode_001",
          "validation_scope": "tsfreq",
          "expectation": "One imaginary mode follows the declared reaction coordinate.",
          "required_evidence_roles": ["tsfreq_gate"]
        }
      ],
      "required_evidence": ["tsfreq_gate"],
      "uncertainties": ["Connectivity is not yet tested."],
      "alternative_hypotheses": [],
      "evidence_refs": ["ev_intake_001"]
    },
    "branch_context": {
      "relation": "continue_parent",
      "from_node": "n000",
      "anchor_node": "n000"
    }
  }
}
```

Close a proposal mechanism node with `closure.hypothesis`, normally
`status=ambiguous` until evidence is produced.

## Start Candidate Or Validation Work

Candidate search requires `candidate_kind`. Validation requires
`validation_scope` and prediction IDs whose declared scope matches.

```json
{
  "schema_version": "ts-decision/2",
  "decision_id": "dec_validation_start",
  "action": "start_node",
  "rationale": "Test the declared imaginary-mode prediction.",
  "evidence_refs": ["ev_candidate_001"],
  "report_ref": {"report_id": "rep_...", "workspace_root": "/path/to/workspace"},
  "base_revision": "sha256:...",
  "payload": {
    "node_id": "n003",
    "parent_node": "n002",
    "node_type": "validation",
    "objective": "Produce TS/Freq evidence for pred_mode_001.",
    "validation_scope": "tsfreq",
    "hypothesis_ref": {
      "hypothesis_id": "hyp_0001",
      "prediction_ids": ["pred_mode_001"]
    },
    "branch_context": {
      "relation": "continue_parent",
      "from_node": "n002",
      "anchor_node": "n002"
    },
    "expected_evidence": ["gaussian_output", "imaginary_mode_summary"]
  }
}
```

Candidate and validation closures may record `closure.program` only. They must
not contain `closure.hypothesis` or `closure.audit`.

## Interpret Evidence

Open a mechanism node with `mechanism_action=evaluate` after the relevant
validation nodes. Its closure may set:

```json
{
  "hypothesis": {
    "status": "unsupported",
    "summary": "The declared electronic prediction is contradicted.",
    "evidence_refs": ["ev_wavefunction_001"],
    "hypothesis_ref": {
      "hypothesis_id": "hyp_0001",
      "prediction_ids": ["pred_state_001"]
    },
    "revision": {
      "action": "refute_hypothesis",
      "changed_variable": "state_character"
    }
  }
}
```

`unsupported` requires cited contradictory evidence. Missing evidence is
`ambiguous`.

## Audit

Audit scopes are `transition_state`, `elementary_step`, `pathway`, and `study`.
For `node_type=audit, audit_scope=pathway`, `payload.pathway_ref` is mandatory.
Before closing a pathway audit, register and cite evidence whose quality
contains a strict accepted or pathway-not-accepted decision. A supported audit
analysis does not by itself mean pathway success.

Audit closures set `closure.audit.status=accepted|not_accepted|ambiguous` and
`study_complete=true|false`. Study completion belongs only to an audit node.

For `audit_scope=pathway`, ambiguity is not a valid closure shortcut. Register
and cite one `pathway_audit_summary` with
`quality.strict_pathway_decision=accepted|pathway_not_accepted`, then set
`closure.audit.status=accepted|not_accepted` to match it. If the discriminator
is unresolved, keep the audit open or stop it without a scientific closure.

## Recalculation

A method change that can alter the scientific conclusion creates a new node:

```json
{
  "node_type": "validation",
  "validation_scope": "method_robustness",
  "attempt_kind": "recalculation",
  "recalculation_ref": {
    "source_node": "n003",
    "source_intent_id": "calc_n003_optfreq_001",
    "changed_settings": ["functional", "basis_set"],
    "purpose": "method_robustness"
  },
  "branch_context": {
    "relation": "recalculation_of",
    "from_node": "n003",
    "anchor_node": "n003"
  }
}
```

A technical retry does not create a recalculation node. Record a new
`ts-calculation-intent/2` attempt with `attempt_kind=retry` under the same node.

## Branch Relations

- `continue_parent`: continue the same scientific object.
- `new_solution_branch`: replace candidate or search strategy under the same
  hypothesis. The start payload must include a new `solution_ref.solution_id`;
  optional `summary`, `strategy`, and `parent_solution_id` describe its lineage.
- `new_hypothesis_branch`: propose an alternative hypothesis.
- `new_pathway_branch`: change pathway topology or elementary-step model. Bind a
  workspace-new `pathway_ref.pathway_id` and retain the source hypothesis.
- `recalculation_of`: refine or challenge a prior result with changed method.

The Root Agent selects the relation. Validators check references, solution
identity, and topology only.

## Apply Sequence

```text
ts_workspace_context -> ts_workspace_decision_draft -> ts_workspace_decision_validate -> ts_workspace_decision_apply
```

Any mutation built from a stale `base_revision` is rejected.

## Historical Lineage Repair

Use `update_workspace.payload.repair_solution_ref` only for a closed historical
`new_solution_branch` created without its required solution identity:

```json
{
  "repair_solution_ref": {
    "node_id": "n004",
    "solution_ref": {
      "solution_id": "sol_n004_recovery",
      "strategy": "fresh_execution_namespace"
    },
    "reason_code": "missing_solution_ref_from_prior_engine"
  }
}
```

The solution ID must be new for that hypothesis. The mutation synchronizes the
node, tree index, and branch event and records an immutable lineage-repair audit.
It is not a general node-edit operation.

Only `ts-decision/2` is accepted. A mechanism hypothesis is created by a
`start_node` decision with `node_type=mechanism`,
`mechanism_action=propose`, and `proposed_hypothesis`.
