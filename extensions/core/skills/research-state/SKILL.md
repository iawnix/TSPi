---
name: research-state
description: Read, validate, and atomically update the canonical TSPi ResearchMap of Phases, Claims, Nodes, Findings, Gates, relations, and focus.
---

# TSPi Research State

[Chinese version](SKILL.zh-CN.md)

Use this Skill for project research state: status queries, object lookup,
ResearchMap validation, bounded Research Memory reads, and atomic changes through
`research_read` and `research_change`. A research workspace must have
`workspace_manifest.json` (`research_state_workspace_2`),
`research_map/context.json` (`research_map_context_2`), and
`lifecycle/liveness.json` (`research_liveness_2`). Context always contains the
array collections `phases`, `claims`, `nodes`, `findings`, `gates`,
`claim_relations`, `attempts`, `artifacts`, `evidence_links`, `lifecycle_actions`,
`claim_assessments`, `claim_revisions`, `strategy_plans`, `strategy_reviews`, and `attempt_interpretations`; `focus.claim_ids`
and `focus.node_ids` are arrays. `memory/index.json` uses
`research_memory_index_1` and is only a metadata/lifecycle projection, never a
second ResearchMap authority. Decision records and the Evidence Registry are
Research State-owned metadata, exposed through `research_read` modes `decisions` and
`evidence` (the internal command IDs are `research.decisions` and
`research.evidence`).

`ResearchClaim`, `ResearchNode`, `Finding`, and `Gate` are the core research
objects. `FactFinding` and `IssueFinding` are typed Finding specializations;
`NodeGate` and `ClaimGate` are typed Gate specializations. A `ResearchPhase` is
an optional navigation group, not a required lifecycle layer. Node state and
outcome represent progress independently of Claim status.

Read with the narrowest `research_read` mode that answers the question. Query
`mode=operations` before an unfamiliar write. Submit every mutation as one
explicit ChangeSet through `research_change`, using `expected_revision` when a
stale write would be unsafe. The Host attaches `principal=root_agent` and
`authority=kernel_write` to the internal Research State request; these authority fields
are not public tool parameters. Never edit canonical workspace documents directly or target a legacy
JSON/SQLite store.

The ChangeSet `type` must be one of the canonical operations in
`references/decision_contract.md`; never invent domain-specific operation names.
For example, a mechanism hypothesis is a `create_claim` operation and a bounded
mechanism study is a `create_node` operation. New Claims start as `proposed`; use `assess_claim` with a reason and registered evidence to record scientific status. Do not use Research State as a capability catalog. Method instructions belong to the active Domain Skill.

For a turn, prefer `context` or `liveness`; expand to `detail`, `decisions`,
`evidence` or `storage` only when the current question requires
it. Attempts and Artifacts are operational evidence: register their manifests
and typed links before citing them in an Interpretation, Finding, or Gate.

The Research State validates references, indexes, graph acyclicity, states, Gate rules,
and the complete post-change map before committing one revision. Findings and
Gate evaluations never change Node or Claim status implicitly. Every attached
NodeGate must have a latest `pass` evaluation before a Node closes with the
`completed` outcome.

## References

- [state_model.md](references/state_model.md): objects, states, and invariants.
- [decision_contract.md](references/decision_contract.md): ChangeSet operations.
- [workspace_contract.md](references/workspace_contract.md): persistence and
  workspace ownership.
- [glossary.md](references/glossary.md): public terminology.

Create or confirm Claim/Node objects before research_strategy references them. A focused scope needs a proposed/active StrategyPlan before execution or evidence writes. If research_decision_required is returned, inspect mode=context, record the missing strategy, and retry only after the prerequisite changes. A successful user_input_required checkpoint is a valid end of this turn; wait for relevant user input rather than issuing the same writes or checkpoint repeatedly.

Routine tool observations do not require Findings. If a fact is needed, first preserve the actual observation with artifact_create or artifact_register; cite the returned artifact_id. On evidence_reference_unknown, inspect research_read mode=evidence. Never replace a missing ID with a tool name or prose. Optional diagnostic failure need not block independent work. For global user_input_required, block the affected Nodes with an explicit reason first; State rejects the checkpoint while independent ready Nodes or running Attempts remain.

For a scientific FactFinding, supply source_refs and nonempty provenance. Registered literature, imported data and computation outputs can be evidence; they need not all have a Job. Plans and untested hypotheses are not confirmed facts. Close completed Nodes with state=closed, outcome=completed and summary before a terminal checkpoint.

Record inspected results with `research_interpretation`. Required fields are
`interpretation.id`, `summary`, `outcome`, an existing Claim ID, and the actual
Attempt ID. Use `outcome` = `supports`, `contradicts`, `inconclusive`, or `invalid`
according to the evidence. Prefer this complete nested form, replacing the example
IDs and summary with the current workspace's records and your assessment:

```json
{
  "interpretation": {
    "kind": "result",
    "result_receipt_ref": "result_<exact ID returned by job_collect>",
    "direct_evidence_refs": ["art_<exact artifact returned by job_collect>"],
    "id": "interpretation_result_1",
    "claim_id": "claim_1",
    "attempt_ref": "attempt_1",
    "summary": "The inspected result supports the claim within the tested conditions.",
    "outcome": "supports"
  }
}
```

`claim_id` and `attempt_ref` must be inside `interpretation`. All public fields use snake_case. `node_id` is optional; when supplied, it must identify an existing
Node linked to the Claim. The optional request `event_id` does not replace the
required interpretation record `id`. Include registered `direct_evidence_refs` when
citing result files; execution success alone does not establish scientific support.

After a demonstrated issue is repaired, use research_change with {"type":"resolve_issue","id":"<existing issue ID>","resolution":"<what changed and how verified>","source_refs":["<registered evidence ID>"]}. source_refs is optional; supplied IDs must exist. This preserves the original issue and evidence, marks it resolved, and records the resolution. Restore affected Nodes separately. Do not invent an update_finding operation or edit State files. A ResearchMap mutation supersedes the prior checkpoint; finish the resumed work with a new checkpoint.

Completion conditions apply to calculation, report and delivery Nodes alike. Legacy dependency_ids requires closed/completed; typed dependencies can explicitly accept finished work. A completion_exemption records a justified exception, not scientific evidence. Query `research_read mode=operations query=evaluate_gate` for nested fields and examples. Batch errors include operation_index and target_id; none of the batch has committed. Keep receipts and repair the rejected operation or prerequisites.

User deliverables use versioned requirements independently of Claims and Node plans. Before planning, review Host sources and installed acceptance profiles; use [requirements.md](references/requirements.md) for source coverage, immutable minimum acceptance, typed dependencies, delivery consumption and honest partial stopping. Read mode=requirements for current fulfillment. Prefer helper-returned prepared_ref and registered artifact_ref instead of copying hashes.
