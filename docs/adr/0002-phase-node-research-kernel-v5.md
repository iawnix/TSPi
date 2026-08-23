# ADR 0002: Phase And ResearchNode Kernel V5

- Status: accepted
- Date: 2026-08-23
- Branch: `ts-dag`
- Supersedes: ADR 0001 for the active protocol; ADR 0001 remains the v4 historical record

## Context

The v4 DAG separated scientific Claims from executable work, but its
`ResearchAct` object still carried too many user-facing meanings. A user could
not quickly map a research question to a stable directory, and the primary Web
view gave the Claim graph and execution graph equal weight. Models also received
more graph detail than they needed for ordinary decisions.

The package needs three distinct answers:

1. Where is this part of the study in the human research narrative?
2. Which bounded unit produced these calculations, files, and outcomes?
3. Which scientific statement is being tested, supported, contradicted, or
   accepted?

One object cannot answer all three without duplicating state or turning labels
into workflow policy.

## Decision

Protocol v5 uses three orthogonal layers:

```text
ResearchPhase -> human navigation and roadmap grouping
ResearchNode  -> bounded work, dependency lineage, attempts, and files
Claim         -> scientific statement, assumptions, falsifiers, and status
```

### ResearchPhase

A ResearchPhase has only an ID, title, objective, creation provenance, and time.
Every ResearchNode references exactly one Phase. A Phase is not a lifecycle
state, enum, permission, scientific gate, or required sequence. Cross-Phase Node
dependencies are valid. The UI may derive counts from Nodes, but it must not
write a Phase status back into canonical state.

### ResearchNode

A ResearchNode owns one bounded objective and principal deliverable. It records
its Phase, zero or more earlier Node dependencies, a primary Claim when one
exists, additional Claim scope, scientific record refs, artifact root, and one
terminal outcome. Node dependencies alone express branches, merges, and
backtracking. Retries that preserve the objective stay under
`nodes/<node_id>/attempts/`; a changed question or deliverable starts another
Node.

ResearchNodes do not duplicate hypothesis text. Hypotheses, assumptions, and
falsifiers belong to Claims so that several Nodes can test the same statement
without copied scientific state.

### Claim And Validation

Claims remain independent of execution. Observations are immutable semantic
records with artifact provenance. GateSpecs are fully expanded and frozen
before deterministic evaluation. Validation does not select the next Node, and
acceptance remains a revision-bound assessment separate from Claim status.

### Authority

The Root Agent selects scientific questions, methods, alternatives,
counterexamples, backtracking, and stopping. The Research Kernel exclusively
allocates IDs, validates refs and schemas, applies Decisions, and persists
canonical state. Compute, Render, Report, remote control, imports, and
notifications are deterministic tools. Compute and Review child sessions are
bounded operational and advisory mechanisms, not scientific state owners.

### Context And Presentation

Default Root context uses a compact workspace brief and focused graph
projections. Full canonical records and artifact excerpts are retrieved only on
demand. Review receives one Claim dossier, not complete workspace files.

`ts_web` is a read-only projection:

- its default view is Phase -> ResearchNode;
- Node details expose Overview, Conclusions, Evidence, Runs, Files, and History;
- Claim relations and the cross-Phase Node DAG are advanced views;
- it never infers a next action, Phase status, Claim status, validation verdict,
  or acceptance.

### Compatibility

V5 is intentionally incompatible with v4. It has no `ResearchAct` reader, field
alias, path alias, automatic migration, or dual-write mode. A v4 workspace must
use its matching release. The active canonical paths are `phases.json`,
`research_nodes.json`, and `nodes/<node_id>/...`.

## Invariants

- Only Decision apply mutates canonical scientific state after bootstrap.
- Every Node references one existing Phase.
- A primary Claim, when present, is also in the Node Claim scope.
- Phase metadata never authorizes an operation.
- Node and Claim DAGs are acyclic and serve different purposes.
- Files, attempts, activities, and Compute runs have one owning Node.
- Review runs have one target Claim and advisory authority only.
- Web, reports, and context are projections, never alternate state stores.

## Consequences

Users can navigate a study and locate files without reading the Claim graph.
Claims can span multiple Nodes, while one Node can test alternatives without
duplicating hypotheses. Context becomes smaller because the default projection
can summarize Phases and focused Nodes instead of serializing every record.

The cost is an additional canonical Phase registry and a required `phaseRef`
when starting a Node. This is accepted because Phase has a deliberately narrow
schema and no behavioral semantics. New scientific domains still extend Claims,
Observations, declarative GateSpecs, and maintained predicates rather than
adding hard-coded workflow branches.

## Validation

The release must verify schema and transaction tests, context budgets, compute
and Review contracts, report projection, package checks, TypeScript typecheck,
and a live desktop/mobile `ts_web` smoke test including refresh and theme
switching.
