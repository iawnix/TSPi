---
name: research-state
description: Read, validate, and atomically update the canonical TSPi ResearchMap of Phases, Claims, Nodes, Findings, Gates, relations, and focus.
---

# TSPi Research Kernel

[Chinese version](SKILL.zh-CN.md)

Use this Skill for project research state: status queries, object lookup,
ResearchMap validation, bounded Research Memory reads, and atomic changes through
`research_read` and `research_change`. A research workspace must have
`workspace_manifest.json` (`research_state_workspace_1`),
`research_map/context.json` (`research_map_context_1`), and
`lifecycle/liveness.json` (`research_liveness_1`). Context always contains the
array collections `phases`, `claims`, `nodes`, `findings`, `gates`,
`claim_relations`, `attempts`, `artifacts`, `evidence_links`, `lifecycle_actions`,
`strategy_plans`, `strategy_reviews`, and `attempt_interpretations`; `focus.claim_ids`
and `focus.node_ids` are arrays. `memory/index.json` uses
`research_memory_index_1` and is only a metadata/lifecycle projection, never a
second ResearchMap authority. Decision records and the Evidence Registry are
Kernel-owned metadata, exposed through `research_read` modes `decisions` and
`evidence` (the internal command IDs are `research.decisions` and
`research.evidence`).

`ResearchClaim`, `ResearchNode`, `Finding`, and `Gate` are the core research
objects. `FactFinding` and `IssueFinding` are typed Finding specializations;
`NodeGate` and `ClaimGate` are typed Gate specializations. A `ResearchPhase` is
an optional navigation group, not a required lifecycle layer. Node state and
outcome represent progress independently of Claim status.

Read with the narrowest `research_read` mode that answers the question. Query
`mode=operations` before an unfamiliar write. Submit every mutation as one
explicit ChangeSet through `research_change`, using `expectedRevision` when a
stale write would be unsafe. The Host attaches `principal=root_agent` and
`authority=kernel_write` to the internal Kernel request; these authority fields
are not public tool parameters. Never edit canonical workspace documents directly or target a legacy
JSON/SQLite store.

The ChangeSet `type` must be one of the canonical operations in
`references/decision_contract.md`; never invent domain-specific operation names.
For example, a mechanism hypothesis is a `create_claim` operation and a bounded
mechanism study is a `create_node` operation. For `research_read` with
`mode=capabilities`, always provide `capabilityKind=compute` or
`capabilityKind=analysis`; these are conditional tool fields, not optional labels.

For a turn, prefer `context` or `liveness`; expand to `detail`, `decisions`,
`evidence`, `storage`, or `capabilities` only when the current question requires
it. Attempts and Artifacts are operational evidence: register their manifests
and typed links before citing them in an Interpretation, Finding, or Gate.

The Kernel validates references, indexes, graph acyclicity, states, Gate rules,
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
