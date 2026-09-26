---
name: tspi-research-kernel
description: Read, validate, and atomically update the canonical TSPi ResearchMap of Phases, Claims, Nodes, Findings, Gates, relations, and focus.
---

# TSPi Research Kernel

[Chinese version](SKILL.zh-CN.md)

Use this Skill for project research state: status queries, object lookup,
ResearchMap validation, bounded Research Memory reads, and atomic changes through
`research_read` and `research_change`. The ResearchMap is the canonical
scientific model; `research.context` and `research.liveness` are disposable
bounded projections, not parallel state. Decision records and the Evidence
Registry are Kernel-owned metadata, exposed through `research.decisions`,
`research.evidence`, and `research.storage`.

`ResearchClaim`, `ResearchNode`, `Finding`, and `Gate` are the core research
objects. `FactFinding` and `IssueFinding` are typed Finding specializations;
`NodeGate` and `ClaimGate` are typed Gate specializations. A `ResearchPhase` is
an optional navigation group, not a required lifecycle layer. Node state and
outcome represent progress independently of Claim status.

Read with the narrowest `research_read` mode that answers the question. Query
`mode=operations` before an unfamiliar write. Submit every mutation as one
explicit ChangeSet through `research_change`, using `expectedRevision` when a stale
write would be unsafe. Never edit `research_map.json` directly.

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
