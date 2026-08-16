# V4 State Model

Protocol v4 separates scientific meaning, deterministic execution, and
presentation. The Root Agent owns interpretation; the Research Kernel owns
identity, integrity, persistence, and transactions.

## Contents

- Claim Graph
- ResearchAct DAG
- Observation
- Finding
- GateSpec And ValidationResult
- Acceptance
- Revisions

## Claim Graph

A Claim is one explicit scientific statement with an open `claim_type`,
assumptions, falsifiers, tags, status, and cited scientific records. Status is a
Root interpretation recorded through a Decision, not a parser or program exit
code.

A ClaimRelation connects two Claims with an open relation label and rationale.
Use it for dependency, refinement, conflict, alternatives, or another explicit
scientific relationship. The Kernel checks refs and acyclicity but never maps a
label to a next action.

## ResearchAct DAG

A ResearchAct records one bounded act:

- objective and optional hypothesis, assumptions, predictions, and falsifiers;
- zero or more dependency Acts;
- related Claims and descriptive tags;
- produced scientific records; deterministic activities are derived from the
  separate Activity Journal by `act_refs`;
- Kernel-owned artifact root `acts/<act_id>`;
- open state or one terminal result.

The Kernel allocates workspace-local IDs in creation order (`act_1`, `act_2`,
...). The ordinal is identity, not a workflow phase, priority, or permission signal.

Multiple dependencies support merges. A new Act depending on an earlier
checkpoint supports backtracking. Preserve failed, blocked, inconclusive, and
stopped Acts; do not rewrite history into a successful line.

ResearchAct uses `ts-research-act/3`. It contains no `operation_refs` field.
The shared Activity Index projects activities from
`acts/<act_id>/activities/*` and `operations/activities/*`, validates journal
integrity, and supplies completion guards, reports, and UI views.

## Observation

An Observation is an immutable semantic assertion:

```text
concept + subject + typed value + unit/qualifiers
  + artifact IDs/digests + producer + creating Act/Decision
```

Use stable domain concepts such as `program.normal_termination` or
`reaction_path.endpoint_assignment`. Do not copy a parser blob into one field
when separate semantic values are required for validation. The Kernel does not
guess aliases for producer-specific keys.

## Finding

A Finding makes an anomaly, conflict, limitation, or open question explicit.
It cites applicable Claims, Acts, and Observations and has severity
`blocking`, `warning`, or `informational`. Resolve it only through a Decision
with a cited explanation. Open blocking Findings prevent acceptance.

## GateSpec And ValidationResult

A GateSpec is a fully expanded validation specification bound to one Claim and
one validation dimension. It freezes checks, success policy, template digest,
predicate-registry digest, and content digest.

A ValidationResult binds a GateSpec digest and selected Observation digests,
then records every deterministic predicate result and aggregate verdict:

```text
pass | fail | inconclusive | error
```

Validation does not update Claim status or choose another Act.

## Acceptance

Claim status and acceptance are separate. An acceptance record snapshots:

- the Claim and digest;
- the versioned acceptance profile and digest;
- all attached GateSpecs and one passing result per specification;
- applicable Findings;
- the creating Decision and summary.

`acceptance_digest` binds the complete record; component digests bind the
Claim, profile, GateSpecs, ValidationResults, and Finding snapshot separately.

Acceptance requires a supported Claim, at least one GateSpec, and the latest
passing result for every attached specification. Changing the Claim,
specifications, latest results, profile, or any relevant Finding requires a new
assessment. Existing records remain immutable history, but only an exact match
to current canonical state is projected as current acceptance.

## Revisions

`workspace_revision` covers canonical v4 documents. `operational_revision`
covers activity such as calculations, Review, and controls. A new operational
record cannot silently change scientific state.

The Pi conversation is neither revision. It may discuss ideas not yet committed
and may omit older records. Recompile graph context rather than treating the
transcript as canonical science.
