# ADR 0003: Minimal Research Kernel And Gate Contracts

[English](0003-minimal-research-kernel-and-gates.md) | [简体中文](0003-minimal-research-kernel-and-gates.zh-CN.md)

- Status: proposed
- Date: 2026-09-16
- Supersedes: the implicit assumption that execution, validation, and research state
  must live in one Kernel surface

## Context

The current Kernel has accumulated workspace state, deterministic validation,
calculation backends, remote scheduling, rendering, reports, and notification
helpers. That makes the Kernel look like a second agent runtime and makes the
Research Map expose implementation details instead of the research trajectory.

The research model needs a smaller boundary. A Root Agent should be able to
state a Claim or Hypothesis, derive a bounded ResearchNode, run tools, and close
that Node with an explicit outcome. Tools such as `ts_calc`, `ts_remote`,
`ts_render`, and `ts_email` are execution capabilities selected through Skills
and Plugins; they should not own scientific state or decide that a Claim is true.

The existing `ProofSpec`, `ValidationResult`, and `Acceptance` records already
cover most claim-level validation. Adding separate NodeGate and ClaimGate
objects without a common contract would create another parallel state machine.

## Decision

### Kernel responsibility

The Research Kernel is the transaction and integrity boundary for:

- Claims, ResearchNodes, Observations, Findings, and their references;
- allocation of stable IDs, workspace-relative artifact ownership, and revisions;
- compilation and freezing of gate definitions;
- deterministic gate evaluation over explicitly referenced records; and
- read-only projections such as the Research Map trajectory.

The Kernel does not choose a scientific method, select the next Node, run a
backend, submit a remote job, send mail, render a figure, or infer Claim status
from a successful tool call. Those are Agent decisions or Skill/Plugin tools.
At the Agent boundary the Kernel is one guarded tool surface (`ts_state` and
`ts_change`): it also manages workspace identity, Node artifact roots, and
transaction-safe working-directory ownership, but it is not another agent
runtime.

The minimum state flow is:

```text
Claim / Hypothesis
        |
        v
ResearchNode (bounded question and deliverable)
        |
        +--> Skill / Plugin runs --> artifacts and operational records
        |
        +--> verified Observations / Findings
        |
        +--> NodeGate --> Node outcome
                         |
                         +--> ClaimGate --> Claim interpretation
```

`Hypothesis` is normally a proposed Claim (`status=proposed`), not a second
scientific record type. `Evidence` is the semantic role of a verified
Observation or declared Finding; an Attempt, Activity, Run, or raw artifact is
execution provenance until the Root Agent verifies and promotes it.

### One Gate contract

NodeGate and ClaimGate are two scopes of the same contract:

```text
GateSpec   = frozen completion or evaluation criteria
GateResult = one digest-bound evaluation of a GateSpec
scope      = node | claim
```

`gate_spec.schema.json` and `gate_result.schema.json` define this shape. The
Kernel evaluates these shapes as deterministic projections and also accepts
explicit `freeze_gate` / `evaluate_gate` mutations. Those mutations lazily add
`gate_specs.json` and `gate_results.json`; existing workspaces remain valid
without either file and do not need duplicated gate fields on every Claim/Node.

Each `GateSpec` contains a target, an optional named profile, an ordered set of
versioned predicates and parameters, a success policy, and a content digest.
The target is exactly one Node for `scope=node` or exactly one Claim for
`scope=claim`. A `GateResult` repeats the target and scope, binds the GateSpec
digest and input revision, records each check and its evidence refs, and has one
of four verdicts:

```text
pass | fail | inconclusive | blocked
```

`blocked` means the gate could not be fairly evaluated because a required
precondition or tool result is missing. It is not a scientific refutation.

### How gates are produced

Gate production is a three-party contract:

1. The Root Agent chooses the research intent and a gate profile, for example
   “record the requested deliverable and leave no owned run pending” or “test
   the Claim's connectivity and stationary-point dimensions.”
2. Skills and Plugins advertise capabilities, input/output schemas, and the
   predicates they can support. They may produce artifacts and observations,
   but they cannot silently create a gate or alter its verdict.
3. The Kernel resolves the profile against the installed predicate registry,
   expands parameters, validates target refs, and freezes the `GateSpec` with a
   digest before evaluation. Later tool results can only be inputs to a new
   `GateResult`; they cannot mutate the frozen criteria.

For a Node, the NodeGate is created when the Node's completion criteria are
declared (at Node creation or before close). The close operation evaluates it
against Node-owned runs, Findings, Observations, and artifacts. When an
explicit NodeGate exists, a latest `pass` GateResult is required before a
terminal Node outcome; it does not imply that the primary Claim is supported.

For a Claim, the ClaimGate is created when the Claim's test profile is
pre-registered or when a new validation dimension is explicitly opened. Its
checks normally compile existing `ProofSpec` definitions. A ClaimGate result
aggregates `ValidationResult` records and other declared evidence. The Root
Agent still decides whether to update the Claim to `supported`, `contradicted`,
or `inconclusive`, and whether to create an immutable Acceptance record.

### Mapping to the current model

The transition deliberately reuses existing records:

| Target concept | Current implementation |
| --- | --- |
| NodeGate criteria | Node completion blockers and terminal-result validation |
| ClaimGate criteria | `ProofSpec` plus the acceptance profile |
| Gate check execution | `ValidationResult` and deterministic Node checks |
| Gate history | `gate_specs.json`, `gate_results.json`, Node result, Claim history, and Acceptance snapshots |
| Tool execution | Attempt, Activity, Agent Run, and artifact records |

`ProofSpec`, `ValidationResult`, and `Acceptance` remain supported APIs during
the transition. Gate registries are now an additive compatibility layer: their
first write is transactional and old workspaces remain replayable without
them. A future protocol revision may still embed immutable refs in Node/Claim
history, but it must preserve this replay rule.

### Research Map boundary

The Research Map consumes a projection of Claim, Node, Observation, GateResult,
and dependency history. It shows what question was opened, which Node produced
which tool run and evidence, the Node outcome, what gate was attempted, and
where the trajectory is blocked, inconclusive, or stale. It does not expose every backend operation and does not infer a
next action from labels, phase names, or a tool's exit status. Phase remains a
navigation grouping only; it is not another gate or lifecycle state.

## Invariants

- A GateSpec is immutable after freezing; changing criteria creates a new spec.
- A GateResult is bound to one GateSpec digest and one input revision.
- NodeGate `pass` is necessary only for Node closure and never changes Claim status.
- ClaimGate verdicts do not automatically mutate Claim status or create Acceptance.
- Plugins own execution records and artifacts; the Kernel owns promoted semantic refs.
- Old workspaces remain valid without GateSpec/GateResult records; explicit gate
  registries are additive and lazy.
- Web, reports, and context consume projections and never become a second gate evaluator.

## Consequences

The Kernel becomes a small, comprehensible scientific state boundary while the
execution plane can grow through Skills and Plugins. Node and Claim completion
are visibly different, but they share digest, revision, and verdict semantics.
The compatibility cost is bounded: protocol-6 workspaces use derived views
until an explicit gate mutation lazily creates the two registries.

## Validation

The implementation validates both standalone schemas, scope/target
invariants, digest fields, release packaging, deterministic evaluation, and
transactional freeze/evaluate operations. Research Map projection tests cover
Node/Claim Gate status, tool/evidence trace, outcomes, and stale results without
introducing a second mutation boundary.
