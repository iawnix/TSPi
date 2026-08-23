# V5 State Model

Protocol v5 separates scientific meaning, deterministic execution, and
presentation. The Root Agent owns interpretation; the Research Kernel owns
identity, integrity, persistence, and transactions.

## Contents

- Decision Identity
- Claim Graph
- ResearchPhase Roadmap
- ResearchNode DAG
- Observation
- Finding
- GateSpec And ValidationResult
- Acceptance
- Revisions

## Decision Identity

The Kernel allocates workspace-local Decision IDs (`dec_1`, `dec_2`, ...).
Their ordinal is immutable identity only, not research order, priority, or a
workflow phase. Drafting does not reserve an ID: parallel drafts may receive the
same next ordinal, but only identical content can replay it after one commits.
Conflicting content must be redrafted. Durable committed, aborted, and
recoverable transaction IDs are not reused.

## Claim Graph

A Claim is one explicit scientific statement with an open `claim_type`,
assumptions, falsifiers, tags, status, and cited scientific records. Status is a
Root interpretation recorded through a Decision, not a parser or program exit
code.

A ClaimRelation connects two Claims with an open relation label and rationale.
Use it for dependency, refinement, conflict, alternatives, or another explicit
scientific relationship. The Kernel checks refs and acyclicity but never maps a
label to a next action.

ClaimRelation IDs use workspace-local creation ordinals (`rel_1`, `rel_2`, ...).

The Kernel allocates workspace-local Claim IDs in creation order (`claim_1`,
`claim_2`, ...). Claim uses `ts-claim/3`; its ordinal is identity only, not
confidence, priority, hierarchy, or a ResearchPhase.

`ResearchNode.claim_refs` is declared research scope. `Claim.created_by_node` is
origin provenance for a Claim discovered during a Node. The canonical fields
are intentionally not mirrored. Context and UI projections derive related
Claim-Node pairs from their union, so either relationship remains traversable
without synchronizing duplicate state.

## ResearchPhase Roadmap

A ResearchPhase has one readable ID (`phase_1`, `phase_2`, ...), title,
objective, creation Decision, and timestamp. Every ResearchNode references one
Phase. Phases organize the human roadmap only: they have no status, successor,
allowed method, required validation, or action authority. Cross-Phase Node
dependencies are valid.

## ResearchNode DAG

A ResearchNode records one bounded node:

- one Phase, short title, objective, and principal deliverable;
- zero or more dependency Nodes;
- optional primary Claim, related Claim scope, and descriptive tags;
- produced scientific records; deterministic activities are derived from the
  separate Activity Journal by `node_refs`;
- Kernel-owned artifact root `nodes/<node_id>`;
- open state or one terminal result.

The Kernel allocates workspace-local Node IDs in creation order (`node_1`,
`node_2`, ...). The ordinal is identity, not a ResearchPhase, priority, or
permission signal.

Multiple dependencies support merges. A new Node depending on an earlier
checkpoint supports backtracking. Preserve failed, blocked, inconclusive, and
stopped Nodes; do not rewrite history into a successful line.

Node granularity is semantic, not a fixed attempt count. One Node should own one
principal scientific question and deliverable. Retries that preserve that
objective remain calculation Attempts below the Node; a changed objective or
principal deliverable starts a dependent Node. Hypotheses, assumptions, and
falsifiers remain on Claims. This guidance preserves
discoverability without turning Node labels or tags into a workflow policy.

ResearchNode uses `ts-research-node/1`. It contains no `operation_refs` field.
The shared Activity Index projects activities from
`nodes/<node_id>/activities/*` and `operations/activities/*`, validates journal
integrity, and supplies completion guards, reports, and UI views.

The read-only Research Files locator joins Claim, Node, Observation, logical
artifact, and calculation-intent identities to their current paths. Attempt
results distinguish frozen inputs from produced outputs. The projection is
rebuilt from canonical records and the artifact catalog, creates no new state,
and never treats every file owned by a related Node as evidence for a Claim.

## Observation

An Observation is an immutable semantic assertion:

```text
concept + subject + typed value + unit/qualifiers
  + artifact IDs/digests + producer + creating Node/Decision
```

Use stable domain concepts such as `program.normal_termination` or
`reaction_path.endpoint_assignment`. Do not copy a parser blob into one field
when separate semantic values are required for validation. The Kernel does not
guess aliases for producer-specific keys.

The Kernel allocates workspace-local Observation IDs in creation order
(`obs_1`, `obs_2`, ...). The ID is a readable reference; scientific meaning
remains in `concept_id`, `subject_ref`, value, and summary.

## Finding

A Finding makes an anomaly, conflict, limitation, or open question explicit.
It cites applicable Claims, Nodes, and Observations and has severity
`blocking`, `warning`, or `informational`. Resolve it only through a Decision
with a cited explanation. Open blocking Findings prevent acceptance.
Finding IDs use workspace-local creation ordinals (`fnd_1`, `fnd_2`, ...).

## GateSpec And ValidationResult

A GateSpec is a fully expanded validation specification bound to one Claim and
one validation dimension. It freezes checks, success policy, template digest,
predicate-registry digest, and content digest.

A ValidationResult binds a GateSpec digest and selected Observation digests,
then records every deterministic predicate result and aggregate verdict:

```text
pass | fail | inconclusive | error
```

Validation does not update Claim status or choose another Node.

GateSpecs and ValidationResults use workspace-local creation ordinals
(`gsp_1`, `gsp_2`, ... and `val_1`, `val_2`, ...). Their dimensions, titles,
checks, and verdicts carry meaning; the ordinal does not rank scientific value.

## Acceptance

Claim status and acceptance are separate. An acceptance record snapshots:

- the Claim and digest;
- the versioned acceptance profile and digest;
- all attached GateSpecs and one passing result per specification;
- applicable Findings;
- the creating Decision and summary.

`acceptance_digest` binds the complete record; component digests bind the
Claim, profile, GateSpecs, ValidationResults, and Finding snapshot separately.

Acceptance records use workspace-local creation ordinals (`acc_1`, `acc_2`,
...) in both their IDs and canonical filenames.

Acceptance requires a supported Claim, at least one GateSpec, and the latest
passing result for every attached specification. Changing the Claim,
specifications, latest results, profile, or any relevant Finding requires a new
assessment. Existing records remain immutable history, but only an exact match
to current canonical state is projected as current acceptance.

## Revisions

`workspace_revision` covers canonical v5 documents. `operational_revision`
covers activity such as calculations, Review, and controls. A new operational
record cannot silently change scientific state.

The Pi conversation is neither revision. It may discuss ideas not yet committed
and may omit older records. Recompile graph context rather than treating the
transcript as canonical science.
