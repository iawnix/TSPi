# ADR 0001: DAG Research Kernel And Declarative Validation

- Status: accepted for the `ts-dag` branch
- Date: 2026-08-15
- Scope: `@iawnix/ts-agent` v4 runtime and canonical workspace

## Decision

Version 4 is a clean protocol boundary. It does not read, write, migrate, or
alias v2/v3 scientific state. A previous release is the rollback mechanism.

The package is a trustworthy scientific execution and evidence runtime. The
Root Agent owns research strategy; deterministic code owns state integrity,
execution effects, evidence provenance, validation, and reproducibility.

```text
Root Agent
  native planning, hypotheses, counterexample search
        |
Research Kernel
  Claim graph + ResearchAct DAG + Decision + Finding
        |
        +-- deterministic execution plane
        +-- Observation plane
        +-- Validation Engine
        +-- Context Compiler
        +-- independent advisory Review Agent
```

Compute, Render, and Report are direct deterministic tools. Review is the only
child model session in the initial v4 runtime. A future model-based analyst,
writer, or designer must be read-only and advisory; it cannot become an
alternate canonical writer.

## Canonical Model

The Kernel owns these canonical documents:

```text
workspace.json
research_state.json
claims.json
claim_relations.json
research_acts.json
observations.json
validation_specs.json
validation_results.json
findings.json
acceptances/
decisions/
decision_log.jsonl
transaction_log.jsonl
```

A `ResearchAct` is a bounded, auditable act with zero or more dependency Acts.
Multiple dependencies model merges; a new Act that cites an earlier checkpoint
models backtracking without rewriting history. The dependency relation is a
DAG. It does not select the next action.

A Claim is a scientific statement. Claim relations form a separate DAG and
record dependency, refinement, conflict, or alternative context. Relation
labels remain scientific metadata and never authorize a workflow transition.

An Observation is an immutable semantic assertion with a `concept_id`, subject,
typed value, optional unit and qualifiers, artifact bindings, and provenance.
The Kernel does not guess aliases for parser field names. Producers must emit a
declared concept directly.

A Finding records an anomaly, limitation, conflict, or unresolved question.
Open blocking Findings are first-class acceptance blockers rather than prose
hidden in a report.

## Decisions And Identity

Only `ts_workspace_decision_apply` writes canonical science. One
`ts-research-decision/1` contains an ordered list of typed operations and is
bound to one Context projection and one base scientific revision.

The draft endpoint allocates every technical identifier. Callers may use local
aliases within a draft; the Kernel resolves them to immutable identifiers before
returning the Decision. Validate executes the same mutation path against a
temporary copy. Apply repeats validation under the workspace lock and commits
atomically. Reusing a Decision ID is idempotent only when the complete Decision
digest matches.

The Kernel persists concise hypotheses, assumptions, predictions, falsifiers,
decisions, and provenance. It never persists private chain-of-thought.

## Validation Engine

Validation is one engine, not a growing switch statement of workflow Gates:

```text
versioned template
  + caller parameters
  -> fully expanded frozen GateSpec
  -> registered deterministic predicates
  -> immutable ValidationResult
```

An Agent may select a packaged template or compose a declarative GateSpec from
registered predicates. It may not supply Python, shell, expressions, imports,
or executable plugin code. Adding a new predicate requires maintained package
code and tests.

Every frozen GateSpec records its template digest when applicable, the
predicate-registry digest, and its own canonical digest. Every result records
the GateSpec digest, selected Observation digests, predicate outcomes, and one
of four verdicts:

```text
pass | fail | inconclusive | error
```

`inconclusive` means the selected valid inputs cannot decide the check. `error`
means the check could not be executed as specified. They are not aliases.

Acceptance uses a versioned profile. A Claim can receive a current acceptance
only when:

1. its explicit status is `supported` and at least one GateSpec is attached;
2. every frozen GateSpec attached to it has a latest passing result;
3. the profile's foundational dimensions are present and passing;
4. no unresolved blocking Finding applies to the Claim;
5. every cited digest and target binding is current.

An acceptance file is an immutable historical assessment, not a permanent
boolean on the Claim. `research_state.acceptance_refs` indexes all records.
Context, Report, and Web derive current records through one Kernel function.
Changing the Claim, attached specifications, latest results, profile, or
relevant Finding snapshot makes an earlier record historical without deleting
it or invalidating the workspace.

Built-in classical TS checks are templates, not privileged workflow branches.
Photochemical, metal-catalyzed, radical, crossing, or dynamics studies extend
the same engine with templates and maintained predicates.

## Context Compiler

The model receives a revision-bound graph projection, not a dump of canonical
files and not counts that imply a prescribed workflow. Kernel graph projections
are `frontier`, `claim`, `act`, `subgraph`, `finding`, `validation`, and
`delta`. The public context tool also exposes deterministic artifact,
compute-capability, and validation-capability catalogs through the same
read-only entry point.

The default frontier contains focus Claims and Acts, direct dependencies and
alternatives, open Findings, incomplete validation, unresolved remote controls,
and the recent object-level Decision delta. Every bounded projection reports
omitted counts and retrieval hints. The Pi transcript is conversational state,
not scientific source of truth.

## Consequences

- The v4 startup rejects legacy or partial canonical state.
- `Node`, `required_gates`, fixed Gate enums, phase/stage/lifecycle routing,
  evidence roles/layers, and scientific fact alias guessing leave the runtime.
- Paths and filenames remain Kernel-owned; public calls use logical IDs.
- Existing v3 workspaces must continue with a v3 release or begin a new v4
  workspace. This branch deliberately contains no migration command.
- Refactoring is complete only when package docs, Skill references, UI wording,
  report projection, tests, and release contents describe this same model.
