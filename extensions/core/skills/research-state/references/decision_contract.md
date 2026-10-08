# ChangeSet Contract

`research_change` is the only public mutation boundary for `ResearchMap`. Its
public payload contains `rationale`, optional `basis_refs`, optional
`expected_revision`, and a non-empty `operations` array. The Host attaches
`principal=root_agent` and `authority=kernel_write` to the internal Research State
request; those authority fields are not public tool parameters. Query
`research_read mode=operations` for the current catalog before using an unfamiliar
operation.

## Operations

Each operation uses `type` and an explicit project-local `id` for objects it
creates. References use the IDs already present in the map.

| Type | Required data |
| --- | --- |
| `create_phase` | `id`, `title`; optional `objective` |
| `create_claim` | `id`, `statement`; optional `status`, `predictions`, `falsifiers` |
| `create_node` | `id`, `title`, `objective`; optional `phase_id`, `claim_ids`, `dependency_ids` |
| `create_finding` | `id`, `node_id`, `statement`, `kind` (`fact` or `issue`); fact fields are `value`, `datatype`, `unit`, `provenance`; issue fields are `status`, `severity`, `resolution` |
| `create_gate` | `id`, `scope` (`node` or `claim`), `target_id`, `criteria` |
| `evaluate_gate` | `gate_id`, `verdict`, `assessments`, optional `message`, `evidence_refs` |
| `set_node_state` | `node_id`, `state`; closing also needs `outcome` and `summary` |
| `set_claim_status` | `claim_id`, `status` |
| `relate_claims` | `source_id`, `target_id`, `relation` |
| `set_focus` | `claim_ids`, `node_ids` |

Object IDs must be unique within the map and references must resolve in the
proposed post-state. Operations run in order, so a later operation can refer to
an object created earlier in the same request. Keep one coherent research change in a
single ChangeSet; unrelated changes should use separate requests.

## Commit Rules

The Research State locks the workspace, loads canonical context, checks
`expected_revision` when present, applies operations to a detached copy, runs
the full map validator, increments `revision`, and atomically replaces context,
liveness, memory, and manifest revision. A rejected request does not alter the
prior map. Do not edit canonical documents directly.

`create_finding` records the Node's verified output. It is not a generic log
entry: use `FactFinding` for a value that supports a scientific statement and
`IssueFinding` for a limitation, anomaly, conflict, or unresolved question.
`create_gate` and `evaluate_gate` are the Gate lifecycle. Claim status and Gate
verdict are independent: a Gate evaluation does not silently change a Claim.


Before starting a calculation, attach explicit Gate criteria to its Node or give
`completion_exemption` with a reason when creating that Node. Each criterion has
an `id` and `source_type`: `runtime_fact`, `validator_result`, or `agent_assessment`.
An evaluation supplies `assessments` for every criterion. Machine criteria require
the actual `result_receipt_ref`; an agent assessment needs a reason and remains an
agent judgment. Use `revise_gate` with `criteria` and `reason` to change conditions;
old versions remain in the audit and previous evaluations no longer pass.

`context` is a bounded current decision view. Use `detail` for an exact object,
`evidence` with `attempt_id` or `job_id`, and `offset`/`limit` for pages. Record goal
`source_refs` and `constraints` on Claims so they survive conversation compaction.
Never copy producer IDs onto agent-created text. `job_collect` certifies current
outputs and returns a stable result receipt. Final `kind=result` interpretations
must cite that receipt and its direct outputs. Use comparison/background roles
for other runs. `kind=observation` or `execution_issue` requires the runtime's
`execution_observation_ref`. Use `supersedes_id` to correct earlier explanations.
Changed outputs invalidate dependent explanations and machine Gate assessments.

Completion conditions also apply to report and email Nodes. Each agent_assessment supplies criterion_id, verdict (pass/fail/inconclusive/blocked), and reason; machine assessments supply criterion_id and result_receipt_ref. Query mode=operations query=evaluate_gate for the complete schema and example, replacing example evidence IDs with registered IDs. Use operation_index/target_id to diagnose an atomic batch failure; rollback does not mean an earlier Gate evaluation was invalid.
