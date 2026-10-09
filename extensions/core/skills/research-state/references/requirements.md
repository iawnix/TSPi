## User requirements and delivery

Worker admission records actual user messages as immutable sources. Read `mode=sources` and
`mode=profiles`; preserve each requested deliverable with `create_requirement`,
its exact `source_quote`, explicit constraints and input Artifact IDs. An
`acceptance_profile` (`id`, `version`) is an optional template. Register the
requirement even if no template or execution capability exists. Empty criteria or
an unresolved template leave it unmet. Review remaining messages with `review_source`
and a reason when they introduce no new deliverable. Creation already associates
the source with the new requirement. If explicitly reviewing recorded requirements,
create them first and include all their IDs. Operations execute in order; a rejected
batch commits nothing. Correct its reported operation and retry at the current revision. Source review is an Agent
judgment: verify coverage against the original message, independently of your plan.
Never downgrade a computational task to `research.material@1` (material-only work).

Bind contributing Nodes with `bind_requirement`. `revise_requirement` adds scope,
criteria or an optional template; it cannot replace original checks or constraints,
remove inputs, or disable execution_required. To resolve a formerly unavailable
template, revise using the same exact profile identity after installation.

For task-composed acceptance, use `criteria` with the same `id`, `source_type`
and fields as Gate criteria: `runtime_fact`, `validator_result`, `agent_assessment`.
Set `execution_required=true` for a requested computation. This adds successful
execution and complete collection checks against the same scoped Attempt; a
validator run alone does not replace the requested computation. Use false for
report writing, interpretation and email delivery; check the report Artifact and
persistent delivery receipt with explicit criteria instead. Keep those deliverables
separate from the computation requirement. Define task-specific criteria at creation
when known, so execution facts are not mistaken for scientific acceptance. Add criteria that
inspect the scientific deliverable, using a registered validator where available.
Validator criteria can declare exact expected `bindings`. They need no profile.
Declare the Job's `input_artifact_ids` and stage the actual files in `inputs`;
Runtime checks their content and binds the input evidence versions to the Attempt.

`assess_requirement` consumes collected `result_receipt_refs`. Provide Agent
judgments in `assessments` with `criterion_id`, `verdict`, and an evidence-based
`reason`. Task constraints without template-owned checks require an assessment
of `requirement.constraints`. Machine verdicts are derived from evidence and
cannot be overridden. Scientific interpretation and extraction completeness
remain Agent judgments; a successful process alone cannot prove them.

Read `mode=requirements` for coverage and current checks. An empty requirement
list is never reported as satisfied, even when a status question is reviewed.
Stage Nodes may finish before a requirement. Gate edits never exempt minimum
acceptance. A completed delivery keeps its historical `requirement_consumption` version and
assessment; new evidence or expanded scope invalidates current acceptance without
rewriting that past delivery. New scoped Attempts invalidate earlier failure stops.
Claim conclusions
remain separate and can be inconclusive even after the requested analysis finishes.

Delivery Nodes declare `consumes.requirement_ids` or `consumes.artifact_refs`, or
explicit predecessor dependencies. Dependencies use `{node_id, condition}` with
`completed` (closed/completed) or `finished` (closed/completed, inconclusive or
stopped). A blocked Node is unfinished.
Use `consumes.condition="observed"` for an authorized status report about blocked
or failed work. A success report consumes satisfied requirements. Email preparation
binds the event to current consumed state; prepare again after relevant state changes.

`record_requirement_stop` preserves unmet work with supported cancellation,
execution-failure or demonstrated capability evidence; `resume_requirement` reopens
it. Missing inputs or an untried method do not prove unavailability. Unsupported
budget claims cannot authorize a stop. Terminal means the run has settled, not that
all science succeeded. Report unmet requirements on partial/cancelled closure.
Missing requirements cannot establish successful acceptance.

Prefer exact persistent `artifact_ref` values such as `a1` in typed Artifact fields
and `prepared_ref` such as `p1` returned by `job_start`. Preparation helpers return
`request_file` and `request_sha256`; submit that pair and the Node ID unchanged.
They are workspace-local immutable registry entries, not fuzzy hash prefixes.
Modified request files or inputs require a new prepared record. Query
`mode=operations query=<operation>` for complete current fields before unfamiliar writes.
