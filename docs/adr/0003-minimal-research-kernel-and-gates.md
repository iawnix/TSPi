# ADR 0003: Minimal ResearchMap And Gate Contracts

[English](0003-minimal-research-kernel-and-gates.md) | [简体中文](0003-minimal-research-kernel-and-gates.zh-CN.md)

- Status: accepted
- Date: 2026-09-16

## Decision

`ResearchKernel` is the transaction and integrity boundary for one canonical
`ResearchMap`. The map is a typed aggregate. `research.db` is the authoritative
Research Memory backend after bootstrap; `research_map.json` is the synchronized
portable snapshot and export. Execution records under `nodes/<node_id>/` remain
outside the scientific aggregate, while bounded decision and evidence metadata
is stored in the same Research Memory backend.

The map owns these concepts:

```text
ResearchPhase       navigation grouping
ResearchClaim       scientific statement and status
ResearchNode        bounded question, work state, and outcome
FactFinding         confirmed Node output
IssueFinding        problem, contradiction, or risk output
Gate                common target/criteria/evaluation contract
  NodeGate          Gate specialized for a ResearchNode
  ClaimGate         Gate specialized for a ResearchClaim
```

`Finding` is one base data structure. The `kind` and specialized fields make a
fact or issue explicit without creating separate registries. `Gate` is likewise
one base contract; `scope` and the specialized class identify its target.

`ResearchMap.to_dict()` is the canonical map serialization. RootAgent and TS Web
read that projection directly; neither builds a second scientific model or
maintains a second mutation store. A client may filter records for presentation,
but filtered data is not a protocol or a mutation boundary. Decision records,
Attempt/Artifact manifests, and Evidence Links are Research Memory metadata,
not duplicate ResearchMap objects and not raw payload copies.

## Gate Semantics

Each Gate has one target, criteria, and an append-only evaluation history. An
evaluation records `pass`, `fail`, `inconclusive`, or `blocked`, the check time,
message, input revision, and evidence references.

`NodeGate` controls whether a Node may close with the `completed` outcome. A
passing NodeGate does not change any Claim. `ClaimGate` records an assessment of
current Findings; the RootAgent explicitly changes the Claim status through a
ChangeSet. Gate evaluation never silently mutates either target.

## Responsibilities

The Kernel validates references and dependency cycles, enforces Node state
transitions, applies optimistic revisions, and atomically commits the active
Research Memory backend plus its JSON snapshot. It does not select a method,
run a Backend, submit a remote job, or infer a Claim status from tool success.

Skills describe procedures and capabilities. Backends implement scientific
software or executors. A Compute Environment is a named local or remote
execution environment with Backend bindings; Platform configuration provides
remote transport and scheduler details. These execution records can point back
to a Node through `attempt_refs` and `artifact_refs`, but they are not additional
scientific object types in the map.

## Invariants

- Every map object has a stable id and creation timestamp.
- Node, Claim, Finding, and Gate references resolve inside the same map.
- Node dependencies and Claim relations are acyclic.
- `ready_nodes()` is derived from Node state and dependencies; it is not stored.
- A closed Node always has an explicit outcome.
- Completing a Node with a NodeGate requires a latest passing evaluation.
- ChangeSets are applied atomically and increment the map revision once.
- `ResearchMap` is the only canonical scientific state model.
- After SQLite bootstrap, `research.db` is the authoritative durable backend;
  `research_map.json` is a synchronized snapshot and portable export.
- Decision, Attempt, Artifact, and Evidence Link metadata is indexed once in
  Research Memory; raw logs and binary payloads stay in their external stores.

## Consequences

The old scientific registry set and view/graph protocol are deliberately not
compatible with this design. TS Web, RootAgent, reports, and future clients
must consume `ResearchMap` serialization and the bounded Research Memory read
models. Operational tooling may keep durable Attempt and Artifact files, but
only the Kernel can register their manifests and promote typed Evidence Links
to Findings or Gate evidence.
