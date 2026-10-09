# ADR 0003: Minimal ResearchMap And Gate Contracts

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

> Historical design record. Research graph and lifecycle guidance is superseded by the [current notebook architecture](../../ARCHITECTURE.md).

[English](0003-minimal-research-state-and-gates.md) | [简体中文](0003-minimal-research-state-and-gates.zh-CN.md)

- Status: accepted
- Date: 2026-09-16

Implementation amendment: canonical mutations use `agent_workspace.py`, shared operation contracts and invariants; the Web view comes from `projection.py`. The former parallel Python classes were removed by [ADR 0010](0010-retire-parallel-runtimes.md).

## Decision

`ResearchState` is the transaction and integrity boundary for one canonical
`ResearchMap`. The map is a schema-validated aggregate serialized in
`research_map/context.json`; `memory/index.json` is only a Research State-owned bounded
metadata/lifecycle projection. Retired SQLite/JSON files are diagnostic inputs,
never a runtime authority. Execution records under `nodes/<node_id>/` remain
outside the scientific aggregate, while bounded decision and evidence metadata
is represented by the ResearchMap collections and projection.

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
one record contract; `scope` and target references identify its target.

`projection.py` creates the canonical ResearchMap view from the validated State context. RootAgent and TS Web
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

The Research State validates references and dependency cycles, enforces Node state
transitions, applies optimistic revisions, and atomically commits the canonical
filesystem context, liveness, and metadata projection. It does not select a method,
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
- Node readiness is derived using the shared dependency predicate; it is not stored.
- A closed Node always has an explicit outcome.
- Completing a Node with a NodeGate requires a latest passing evaluation.
- ChangeSets are applied atomically and increment the map revision once.
- `ResearchMap` is the only canonical scientific state model.
- `research_map/context.json` is the canonical durable scientific state;
  `memory/index.json` is a bounded projection and never a second authority.
- Decision, Attempt, Artifact, and Evidence Link metadata is indexed once in
  the Research State context/projection; raw logs and binary payloads stay in external stores.

## Consequences

The old scientific registry set and view/graph protocol are deliberately not
compatible with this design. TS Web, RootAgent, reports, and future clients
must consume `ResearchMap` serialization and the bounded Research Memory read
models. Operational tooling may keep durable Attempt and Artifact files, but
only the Research State can register their manifests and promote typed Evidence Links
to Findings or Gate evidence.
