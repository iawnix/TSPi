# Root Agent Change Protocol

Root owns scientific judgment. The Kernel owns structural validity and atomic
storage. Keep those responsibilities separate.

## Before A Change

Read the smallest useful `ts_state` result:

```text
summary -> map -> detail/locate -> artifacts/capabilities/runs
```

State the question, the current uncertainty, the Node that owns the work, and
the source records supporting the proposed change. Reuse existing IDs. Create a
new dependent Node when the question, deliverable, or Claim scope changes;
retrying the same calculation remains an Attempt under the same Node.

## During A Change

Submit one `ts_change` request with a concrete rationale and ordered operations.
Use `create_finding` for verified Node outputs and choose `kind=fact` or
`kind=issue`. Keep a Finding's statement narrow and cite `source_refs` such as
Artifact IDs. Use `create_gate` only for a criterion that needs to be visible
in the map, then `evaluate_gate` with the current evidence references.

Do not infer a scientific conclusion from a successful tool return. Check the
primary Artifact and execution record first. A scheduler or parser failure is
operational information; record an IssueFinding only when its scientific impact
has been established.

## After A Change

Read the returned revision and, when useful, `research.summary`. A Node can be
closed as `completed` only when its completion criteria are satisfied and every
attached NodeGate has a passing latest evaluation. Use `inconclusive` or
`stopped` when the question is not resolved. Update Claim status explicitly;
Node state and Claim status do not imply one another.

For a new question, create the successor Node with a dependency on the prior
Node and set focus in the same or a subsequent ChangeSet. Preserve the old
Node, Findings, Gates, Artifacts, and Attempts as history.

## Research Turn Checkpoint

At the end of every turn, read the bounded `research.context` or
`research.liveness` view and make the lifecycle disposition explicit. Record a
concrete next action with `ts_workflow` (`set_required`), leave a submitted
Attempt as `waiting_external`, record `deferred` or `blocked` with its reason,
or close the relevant map scope after interpreting the evidence. Parsed or
completed operational records do not close a scientific question by
themselves. `decision_needed` requires the Root Agent to continue and record a
disposition; a Harness follow-up may enforce that boundary but never chooses a
method. An explicit `required` plan is a valid next-turn checkpoint and must not
be forced to execute in the same turn. Monitor `next_run` is only an operational
wake-up.

## Review

Review is advisory and never writes the map. Give Review only the Claim and
Artifacts it needs, answer it through `ts_reply`, and record Root's accepted,
rejected, or qualified interpretation with ordinary map operations.
