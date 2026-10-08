## User requirements and delivery

Host records actual user messages as immutable sources. Read `mode=sources` and
`mode=profiles`; preserve each requested deliverable with `create_requirement`,
its exact `source_quote`, installed `acceptance_profile` (`id`, `version`), explicit
constraints and input Artifact IDs. Review remaining messages with `review_source`
and a reason when they introduce no new deliverable. Source review is an Agent
judgment: verify coverage against the original message, independently of your plan.
Never downgrade a computational task to `research.material@1` (material-only work).

Bind contributing Nodes with `bind_requirement`. `revise_requirement` adds scope;
it cannot remove original minimum checks, constraints or inputs. `assess_requirement`
consumes actual validator result receipts and derives satisfaction; it accepts no
manual pass override. Read `mode=requirements` for coverage, current checks and
remaining work. Stage Nodes may finish before a requirement. Gate edits and
`completion_exemption` never exempt its minimum acceptance. A completed delivery keeps its historical `requirement_consumption` version and
assessment; new evidence or expanded scope invalidates current acceptance without
rewriting that past delivery. New scoped Attempts invalidate earlier failure stops.
Claim conclusions
remain separate and can be inconclusive even after the requested analysis finishes.

Delivery Nodes declare `consumes.requirement_ids` or `consumes.artifact_refs`, or
explicit predecessor dependencies. Dependencies use `{node_id, condition}` with
`completed` (closed/completed) or `finished` (closed/completed, inconclusive or
stopped); legacy `dependency_ids` means `completed`. A blocked Node is unfinished.
Use `consumes.condition="observed"` for an authorized status report about blocked
or failed work. A success report consumes satisfied requirements. Email preparation
binds the event to current consumed state; prepare again after relevant state changes.

`record_requirement_stop` preserves unmet work with supported cancellation,
execution-failure or demonstrated capability evidence; `resume_requirement` reopens
it. Missing inputs or an untried method do not prove unavailability. Unsupported
budget claims cannot authorize a stop. Terminal means the run has settled, not that
all science succeeded. Report unmet requirements on partial/cancelled closure.
Legacy workspaces remain untracked until original user sources are recovered;
never infer successful acceptance from missing requirements.

Prefer exact persistent `artifact_ref` values such as `a1` in typed Artifact fields
and `prepared_ref` such as `p1` from installed preparation helpers in `job_start`.
They are workspace-local immutable registry entries, not fuzzy hash prefixes.
Modified request files or inputs require a new prepared record. Query
`mode=operations query=<operation>` for complete current fields before unfamiliar writes.
