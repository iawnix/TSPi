# State Model

Persistent node state has three concepts:

- `phase`: the scientific claim layer under test.
- `lifecycle`: whether the node is running, closed, or administratively
  stopped.
- `closure`: the close record written by `end_node`.

Valid phases:

- `endpoint`
- `hypothesis_generation`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`
- `pathway_audit`

`endpoint` is reserved for the mandatory `n000` endpoint and initial-hypothesis
contract. `hypothesis_generation` introduces a later mechanism hypothesis and
must use `branch_context.relation=new_hypothesis_branch`.

R/P conformer or pose exploration is a `candidate_generation` strategy, not a
separate evidence layer. Record it in `solution_ref.strategy` and register
`endpoint_conformer_ensemble`, `selected_endpoint_conformer`, and any relevant
endpoint identity or minimum gates before using a selected conformer downstream.

Legacy `preflight` and `rp_conformer_generation` nodes remain readable and
closable, but new `start_node` decisions must not create them.

`closure.program_status` is an execution fact:

- `completed`
- `failed`
- `stopped`
- `not_run`

`closure.claim_verdict` is the phase-level scientific judgment:

- `supported`
- `refuted`
- `inconclusive`
- `not_evaluated`

For `pathway_audit`, the verdict applies to the audit conclusion, not directly
to the pathway. A supported audit can support a negative conclusion such as
`pathway_not_accepted` or missing connectivity. Views and reports must expose
that audit outcome separately instead of displaying the node as pathway success.
Report aggregation must not count `pathway_audit` verdicts as direct support or
refutation of the audited prediction. Use the underlying elementary-step phases
for `supported_predictions` and `refuted_predictions`; expose audit outcomes in
a separate audit summary. Report summaries may expose branch state such as
`current_branch_not_accepted`, but must not emit next-action recommendations;
branch choice remains an agent decision.

Specific diagnostics such as a wrong imaginary mode, collapsed endpoint,
scheduler failure, parser failure, or RMSD disagreement are reason codes or
evidence diagnostics. They are not top-level node states and must not steer the
framework as fixed branches.

`solution_ref` is optional lineage metadata for grouping alternative search
strategies under the same `hypothesis_ref`. It does not add a lifecycle value,
claim verdict, branch disposition, or retry classification, and it does not
choose `branch_context.relation`. A failed Gaussian route, wrong-basin
TS/Freq result, or exhausted scan remains an execution fact, evidence
diagnostic, closure fact, or decision rationale; the agent must still make an
explicit next decision from the evidence. Same-claim protocol changes (e.g.
different IRC integrator on the same TS/Freq-supported checkpoint) keep the
existing `solution_ref` and use `branch_context.relation = continue_parent`;
they are not a new solution branch.

If the agent decides a failed route is only a solution failure, the next node
keeps the same `hypothesis_ref`, uses a new `solution_ref`, and records
`payload.branch_context.relation=new_solution_branch`. The workspace validates
that referenced nodes exist, that the branch keeps the same `hypothesis_id`,
that `payload.parent_node` equals `payload.branch_context.anchor_node`, and
that the anchor is the current hypothesis `source_node`.
The triggering node remains recorded in `payload.branch_context.from_node`.
The workspace must not infer from node status that a new solution, hypothesis
replacement, or stop decision is required.
