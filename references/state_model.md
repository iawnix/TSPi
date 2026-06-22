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
a separate audit summary.

Specific diagnostics such as a wrong imaginary mode, collapsed endpoint,
scheduler failure, parser failure, or RMSD disagreement are reason codes or
evidence diagnostics. They are not top-level node states and must not steer the
framework as fixed branches.
