# State Model

Persistent node state has three concepts:

- `phase`: the scientific claim layer under test.
- `lifecycle`: whether the node is running, closed, or administratively
  stopped.
- `closure`: the close record written by `end_node`.

Valid phases:

- `preflight`
- `endpoint`
- `rp_conformer_generation`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`
- `pathway_audit`

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
claim verdict, branch disposition, or retry classification. A failed Gaussian
route, wrong-basin TS/Freq result, or exhausted scan remains an execution fact,
evidence diagnostic, closure fact, or decision rationale; the agent must still
make an explicit next decision from the evidence.

If the agent decides a failed route is only a solution failure, the next node
keeps the same `hypothesis_ref`, uses a new `solution_ref`, and records
`payload.branch_context.relation=new_solution_branch`. The workspace may
validate that the referenced nodes exist and that the branch keeps the same
`hypothesis_id`; it must not infer from node status that a new solution,
hypothesis replacement, or stop decision is required.
