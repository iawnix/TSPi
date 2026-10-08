# Root Agent Change Protocol

Root owns scientific judgment. The Research State owns structural validity and atomic
storage. Keep those responsibilities separate.

## Before A Change

Read the smallest useful `research_read` result:

```text
summary -> map -> detail/locate -> evidence
```

State the question, the current uncertainty, the Node that owns the work, and
the source records supporting the proposed change. Reuse existing IDs. Create a
new dependent Node when the question, deliverable, or Claim scope changes;
retrying the same calculation remains an Attempt under the same Node.

## During A Change

Submit one `research_change` request with a concrete rationale and ordered operations.
Use `create_finding` for verified Node outputs and choose `kind=fact` or
`kind=issue`. Keep a Finding's statement narrow and cite `source_refs` such as
Artifact IDs. Use `create_gate` only for a criterion that needs to be visible
in the map, then `evaluate_gate` with the current evidence references.
`source_refs` may contain only registered Artifact or EvidenceLink IDs. Strategy-plan,
Claim, Node, and request IDs are not evidence; use request-level `basis_refs` when a
ChangeSet or strategy is the decision basis instead of placing its ID in a Finding.

Do not infer a scientific conclusion from a successful tool return. Check the
primary Artifact and execution record first. A scheduler or parser failure is
operational information; record an IssueFinding only when its scientific impact
has been established.

## After A Change

Read the returned revision and, when useful, `research_read mode=summary`. A Node can be
closed as `completed` only when its completion criteria are satisfied and every
attached NodeGate has a passing latest evaluation. Use `inconclusive` or
`stopped` when the question is not resolved. Update Claim status explicitly;
Node state and Claim status do not imply one another.

For a new question, create the successor Node with a dependency on the prior
Node and set focus in the same or a subsequent ChangeSet. Preserve the old
Node, Findings, Gates, Artifacts, and Attempts as history.

## Research Turn Checkpoint

At the end of every turn, read the bounded `research_read mode=context` or
`research_read mode=liveness` view, record any needed strategy or Attempt interpretation,
and call `research_checkpoint` with an explicit disposition:
`continue_required`, `waiting_external`, `deferred`, `blocked`, `terminal`, or
`user_input_required`. `research_checkpoint` is the canonical turn checkpoint.
Parsed or completed operational records do not close a scientific question by themselves.
`decision_needed` requires the Root Agent to continue and record a checkpoint.
When liveness also reports `execution_ready=true`, an active StrategyPlan covers
the focused scope and the Root Agent may execute that declared plan before the
checkpoint; the Host still requires the checkpoint before the turn ends. A
Harness follow-up may enforce that boundary but never chooses a method. A
`continue_required` plan is a valid next-turn checkpoint and must not be forced
to execute in the same turn. Monitor `next_run` is only an operational wake-up.

## Review

Review is an isolated advisory assessment and never writes the map. Give it
only the Claim and registered Artifacts it needs. It cannot mutate Claims,
Nodes, Findings, Gates, choose a method, launch/cancel Compute, or serve as
evidence by itself. Answer it through `research_interpretation`, then record Root's
accepted, rejected, or qualified interpretation with ordinary map operations.

`artifact_derive` records a derivation descriptor only. Execute actual analysis with Skill scripts through Job Runtime, then register its outputs.