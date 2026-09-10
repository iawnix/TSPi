# Root Decision Protocol

## Normal Loop

1. Read a frontier or delta projection.
2. Name the unresolved question and possible falsifiers.
3. Select one decision-sized ResearchNode and explicit dependencies.
4. Draft, validate, and apply the graph change.
5. Run deterministic actions, then verify local primary artifacts.
6. Record semantic Observations and Findings.
7. Freeze and evaluate only the validation dimensions relevant to the Claim.
8. Update the Claim and complete the Node with exact cited basis.
9. Decide independently whether to branch, merge, backtrack, stop, or continue.

The Kernel validates this record; it does not supply the strategy.

## Node Boundary Test

Start a new Node when the unresolved question, principal deliverable,
hypothesis scope, independent method branch, backtrack target, or synthesis goal
changes. Keep retries and recalculations in the current Node only when success
would answer the same question with the same deliverable. Several tools and
method variations may serve one question, but
candidate discovery, stationary-point assessment, connectivity, and final
synthesis are not one umbrella Node merely because they concern one Claim.

One Decision may start at most one Node and complete at most one Node. When the
next question follows directly, close the current Node and open its dependent
successor in the same atomic Decision. The dependency is required; unrelated
close/open transitions use separate Decisions. Phase changes mark a new
human-facing question family, not a fixed lifecycle stage.

## Failed Exploration And Backtracking

Preserve the failed Node, operation, output, and Finding. Distinguish an
operational failure from a scientific result. To resume from an earlier point,
start a new Node that depends on the earlier checkpoint and state what changed.
Do not copy or rewrite the failed branch.

Use multiple dependencies when a new Node combines conclusions or artifacts
from several branches. Use Claim relations to preserve competing explanations;
do not force alternatives into one linear Node chain.

## Review

Request Review only for a focused Claim. After successful Review, record one
Root disposition before another scientific mutation:

- `accept`: adopt the advice as a planning input;
- `partially_accept`: identify accepted and rejected parts;
- `reject`: cite why it does not change the plan;
- `defer`: state which missing information prevents a response.

Disposition is operational. Any scientific change still requires verified
Observations and a normal Decision.

## Acceptance

Before `accept_claim`:

1. confirm the Claim status is `supported` and at least one ProofSpec is attached;
2. confirm the latest ValidationResult for each attached ProofSpec passes;
3. confirm the profile's foundational dimensions are present;
4. resolve every applicable blocking Finding;
5. ensure the Claim statement, assumptions, and cited artifacts still match;
6. describe residual scientific limitations in the acceptance summary.

An existing record is historical, not current, after any accepted Claim,
ProofSpec, latest result, profile, or relevant Finding snapshot changes.

Negative, inconclusive, and error verdicts are durable boundaries. They do not
automatically prescribe retry or abandonment.
