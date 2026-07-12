# Agent Decision Protocol

This protocol is for agents using the skill during live transition-state
research. It defines what to read before closing a node and before choosing the
next action.

The workspace is the only trusted state source. Use `report_workspace` as the
decision dashboard, then drill into node and evidence files when a choice
depends on previous success or failure.

## Required Decision Cycle

Before every mutation after bootstrap:

1. Run:

   ```bash
   python scripts/ts_workspace.py report_workspace --root <workspace>
   ```

2. Read the current-node files relevant to the decision:

   - `nodes/<node_id>/node.json`
   - current-node artifacts under `nodes/<node_id>/outputs/`
   - `nodes/<node_id>/outputs/artifact_manifest.json` when this node consumed
     upstream artifacts
   - relevant records in `evidence_registry.json`

3. Read the phase-specific reference named below.
4. Start from a matching file in `templates/decision/`.
5. Write a decision JSON whose `action` matches the command.
6. Run:

   ```bash
   python scripts/ts_workspace.py validate_decision --root <workspace> --decision-file decision.json
   ```

7. Apply exactly one mutation: `start_node`, `update_workspace`, or `end_node`.
8. Run `report_workspace` again before choosing the next action.

Do not infer workspace state from memory. Do not copy JSON from `tests/`.

## Before Closing A Node

Read the current node's phase and use the matching reference:

- `endpoint` or `preflight`: `references/decision_contract.md` and
  `references/mechanism_reflection.md`
- `candidate_generation`: `references/candidate_generation.md`
- `tsfreq_validation`: `references/gaussian_validation.md`
- `connectivity_validation`: `references/connectivity_validation.md`
- `accepted_audit`: `references/workspace_contract.md` and
  `references/mechanism_reflection.md`
- `pathway_audit`: `references/pathway_model.md` and
  `references/report_template.md`

Then choose an `end_*` decision template that matches the evidence actually
available. If a phase is not supported, close it as `refuted`,
`inconclusive`, or `not_evaluated` as appropriate.

Program failures and chemistry failures are different:

- Program failure: scheduler failure, parser failure, route syntax issue,
  optimizer crash, IRC corrector failure. Use `program_status=failed` and
  `claim_verdict=not_evaluated`.
- Chemistry failure: calculation completed but evidence refutes the claim. Use
  `program_status=completed` and the appropriate `claim_verdict`.

## After Closing A Node

Immediately run `report_workspace` and inspect:

- `valid` and `validation_findings`
- `readiness.highest_validated_layer`
- `readiness.blocking_evidence`
- `hypothesis_context.required_next_evidence`
- `hypothesis_context.open_predictions`
- `open_nodes`
- `branch_frontiers`
- `solution_lineage`
- `branch_events`
- `node_index`

Use this report to decide one of:

- `start_node` to continue the same evidence chain;
- `start_node` to open a new solution, hypothesis, or pathway branch;
- `update_workspace` to register missing evidence or perform an explicit
  repair;
- `stop` if no meaningful branch remains or the user asked to stop;
- `ask_user` if the next chemistry decision depends on user preference.

## Seeing Previous Failed Exploration

Within the same workspace, the agent can see previous failed exploration. It is
not all loaded into the prompt automatically, but it is reachable through the
workspace state:

- `report_workspace.node_index` lists all known nodes and their lifecycle,
  phase, verdict, and program status.
- `report_workspace.branch_frontiers` shows closed or stopped nodes and whether
  they already led to a follow-up branch.
- `report_workspace.solution_lineage` groups attempts by hypothesis and
  `solution_ref`.
- `report_workspace.branch_events` records branch provenance, including
  `from_node`, `anchor_node`, `reason_code`, and `changed_variable`.
- `nodes/<failed_node>/node.json` contains closure summaries, program facts,
  mechanism facts, evidence refs, and open questions.
- `evidence_registry.json` links evidence ids to node-scoped artifact paths.
- `decisions/<decision_id>.json` stores the full decision snapshot that created
  or closed a node.
- `decision_log.jsonl` and `transaction_log.jsonl` provide the mutation audit
  trail.

When a previous failure may affect the next decision, read the failed node's
`node.json`, the cited evidence records, and the referenced artifacts before
choosing a branch relation.

Across independent repeated studies, do not reuse old task directories or old
TS structures unless the user explicitly asks for cross-run comparison. The
previous-failed-exploration rule applies inside the active workspace only.

## Choosing The Next Branch Relation

Use `continue_parent` when the same scientific object continues to the next
evidence layer, or when the same TS claim is re-validated with different
program or IRC protocol settings after a program-level failure.

Use `new_solution_branch` only when the candidate or search strategy really
changes under the same hypothesis. It requires a new `solution_ref.solution_id`
and `parent_node == branch_context.anchor_node == hypothesis.source_node`.

Use `new_hypothesis_branch` when the mechanism hypothesis changes.

Use `new_pathway_branch` when the pathway topology or step model changes.

Use `administrative_followup` for monitoring, report packaging, workspace
repair, or visualization. It must not carry a chemistry verdict.

If two or more consecutive nodes under the same hypothesis fail by wrong basin,
route ineffectiveness, ambiguous surface, repeated same-side IRC endpoints, or
route mismatch, read `references/strategy_reflection.md` before opening another
node.

## Template Routing

Use templates as the starting point, not as a policy engine:

- endpoint start/close: `start_endpoint_n000.json`,
  `end_endpoint_n000_supported.json`
- evidence registration: `update_*_evidence.json`
- normal evidence-layer progression: `start_candidate_generation.json`,
  `start_tsfreq_validation.json`,
  `start_connectivity_validation__initial.json`, `start_accepted_audit.json`,
  `start_pathway_audit.json`
- same TS claim with changed IRC/protocol after program failure:
  `start_connectivity_validation__protocol_variant.json`
- real replacement candidate or search strategy:
  `start_solution_branch__strategy_change.json`
- negative pathway audit: `update_pathway_audit_not_accepted.json`,
  `end_pathway_audit_not_accepted.json`

If no template matches, do not force the nearest template. Read
`references/decision_contract.md`, construct the minimal valid decision, and
run `validate_decision` before mutation.
