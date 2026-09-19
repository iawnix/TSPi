# ADR 0001: Phase And ResearchNode Kernel

[English](0001-phase-node-research-kernel.md) | [简体中文](0001-phase-node-research-kernel.zh-CN.md)

- Status: accepted, amended by [ADR 0003](0003-minimal-research-kernel-and-gates.md)
- Date: 2026-08-23
- Branch: `ts-dag`

## Context

The package must separate scientific Claims from executable work without making
one object carry every user-facing meaning. A user must be able to map a
research question to a stable directory, and the primary Web view must preserve
the research narrative. Root and Web consume the same complete canonical
`ResearchMap`; a client may focus its display or prompt context without defining
another scientific model.

The package needs three distinct answers:

1. Where is this part of the study in the human research narrative?
2. Which bounded unit produced these calculations, files, and outcomes?
3. Which scientific statement is being tested, supported, contradicted, or
   left open?

One object cannot answer all three without duplicating state or turning labels
into workflow policy.

## Decision

The research kernel uses three orthogonal map object types:

```text
ResearchPhase -> optional human navigation and roadmap grouping
ResearchNode  -> bounded work, dependency lineage, attempts, and artifacts
ResearchClaim -> scientific statement, predictions, falsifiers, and status
```

### ResearchPhase

A ResearchPhase has a common map-object identity and metadata, a title, an
objective, and a reverse index of its Nodes. A ResearchNode may reference one
Phase through its optional `phase_id`. A Phase is not a lifecycle state, enum,
permission, scientific gate, or required sequence. Cross-Phase Node dependencies
are valid. The UI may derive counts from Nodes, but it must not write a Phase
status back into canonical state.

### ResearchNode

A ResearchNode owns one bounded objective and principal deliverable. It records
an optional `phase_id`, `claim_ids`, `dependency_ids`, `finding_ids`, `gate_ids`,
`attempt_refs`, `artifact_refs`, an explicit state, and an optional terminal
outcome. Node dependencies alone express branches, merges, and backtracking.
Retries that preserve the objective stay under
`nodes/<node_id>/attempts/`; a changed question or deliverable starts another
Node.

The Node is the user-visible bounded research task. A ChangeSet may create or
transition Nodes, and a new Node depends explicitly on any completed Node that
motivated it. Evidence registration, tool calls, and retries remain operational
records and do not become extra roadmap Nodes.

ResearchNodes do not duplicate hypothesis text. Hypotheses, assumptions, and
falsifiers belong to Claims so that several Nodes can test the same statement
without copied scientific state.

### Claim, Findings, And Gates

Claims remain independent of execution. A Node produces `Finding` records,
specialized as `FactFinding` or `IssueFinding`, with artifact provenance. One
`Gate` base type is specialized as `NodeGate` or `ClaimGate`; evaluations are
recorded on the Gate and do not silently mutate the target status.

### Authority

The Root Agent selects scientific questions, methods, alternatives,
counterexamples, backtracking, and stopping. ChangeSet callers supply
workspace-local scientific object IDs. The Research Kernel validates those IDs,
references, schemas, and graph invariants, applies ChangeSets, and persists
canonical state. Compute, Render, Report, remote control, imports, and
notifications are deterministic tools. Compute and Review child sessions are
bounded operational and advisory mechanisms, not scientific state owners.

### Context And Presentation

`ResearchMap.to_dict()` is the canonical serialized map. RootAgent and TS Web
query that document directly; they may choose a focused view but do not create
another scientific state store. The canonical paths are `research_map.json`,
`transactions.jsonl`, and `nodes/<node_id>/...`.

## Invariants

- Only ResearchKernel ChangeSet apply mutates canonical scientific state after bootstrap.
- A Node may reference at most one existing Phase; `phase_id` may be null.
- A Claim may be referenced by many Nodes and a Node may reference many Claims.
- Phase metadata never authorizes an operation.
- Node and Claim DAGs are acyclic and serve different purposes.
- One ChangeSet records explicit Node state transitions.
- Files, attempts, activities, and Compute runs have one owning Node.
- Review runs have one target Claim and advisory authority only.
- Web, reports, and context consume canonical map serialization, never alternate state stores.

## Consequences

Users can navigate a study and locate files without reading every map record.
Claims can span multiple Nodes, while one Node can test alternatives without
duplicating hypotheses. Clients can filter the canonical map without creating
another scientific model.

The cost is an additional optional Phase class and `phase_id` field on a Node.
This is accepted because Phase has a deliberately narrow schema and no
behavioral semantics. New scientific domains extend Finding metadata and Skills
rather than adding hard-coded workflow branches.

## Validation

The release must verify ResearchMap round trips, ChangeSet transactions, Gate
semantics, compute node lookup, package checks, TypeScript typecheck, and a
live `ts_web` smoke test including refresh and theme switching.
