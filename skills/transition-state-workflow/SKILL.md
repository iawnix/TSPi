---
name: transition-state-workflow
description: Auditable TS and reaction-path research in TSPi. Use for candidate search, optimization/frequency/IRC, mechanisms, connectivity, xTB/CREST/ASE/Gaussian, branching, recovery, or v4 continuation.
---

# Transition-State Workflow

Root reasons about chemistry; deterministic code owns graph identity, state,
effects, provenance, and validation.

## Non-Negotiable Boundaries

- Mutate canonical science only through `ts_workspace_decision_apply`.
- Root chooses questions, hypotheses, methods, branches, backtracking,
  stopping, and interpretation. Graph edges and validation never choose the
  next action.
- Treat Claim relations, Act dependencies, and tags as recorded context only.
- Program, scheduler, parser, render, report, and delivery results are
  operational until verified local artifacts support semantic Observations.
- Record anomalies, conflicts, limitations, and unresolved questions as
  Findings. Never hide an acceptance blocker in prose.
- Freeze GateSpecs before evaluation. Review, UI, reports, and historical
  acceptance records remain read-only or advisory.

## Operating Loop

1. Read a `frontier` projection, or `delta` when both prior revisions are known.
2. State one unresolved question, assumptions, predictions, and falsifiers.
3. Create or update Claims and start one bounded ResearchAct with meaningful
   dependencies.
4. Select a method from chemistry, uncertainty, cost, and available artifacts.
5. Run deterministic tools with the owning Act; the Activity Journal derives
   the immutable link from `act_refs`.
6. Verify local primary outputs; record semantic Observations and Findings.
7. Freeze and evaluate GateSpecs over explicit Observation refs.
8. Update Claims, complete the Act only after activity/control checks pass, and
   accept only through a passing named profile.
9. Recompile context and independently choose the next question, branch, merge,
   backtrack, stop, or completion.

Backtrack with a new Act depending on an earlier checkpoint; never erase
history. Act IDs are `act_1`, `act_2`, ...; the ordinal is identity, not phase
or priority.

Do not impose a universal low-cost-first, Gaussian-first, or QST-first sequence. Gaussian
may generate candidates when direct TS optimization, scans, or QST are
justified. Before QST2/QST3, require compatible endpoints, mapping,
conformations, and an elementary-step rationale.

## Decisions

Use the control tools in this order:

1. `ts_workspace_context` for the current bounded projection.
2. `ts_workspace_decision_draft` for Root-authored operations and local aliases.
3. `ts_workspace_decision_validate` for a complete non-mutating dry run.
4. `ts_workspace_decision_apply` for the locked transactional commit.

The draft allocates IDs and resolves `$alias` references. Never invent IDs or
edit the returned `ts-research-decision/1`; any change requires a new draft.
Decision primitives are composable operations, not a prescribed sequence.

## Validation

Use `ts_workspace_context mode=validation_capabilities` to discover registered
predicates, templates, and acceptance profiles. Choose either a packaged,
versioned template with typed parameters or a declarative definition composed
only of registered predicates.

Before a template GateSpec, query its exact `templateId` and `templateVersion`;
the focused result lists parameters and Observation selectors.

The compiler freezes template, registry, content, and selected Observation
digests. Verdicts are `pass`, `fail`, `inconclusive`, or `error`; only `pass`
satisfies a GateSpec. Agent-supplied executable code is forbidden. Acceptance
requires current passing coverage and no applicable open blocking Finding.

## Compute

Before `operation=prepare`, read `ts_workspace_context mode=artifacts` and bind
logical `artifactId` values to required `inputRole` values. `ts_compute`
performs exactly one deterministic operation. The host owns intent IDs, paths,
filenames, manifests, remote directories, and binding checks.

Do not poll unchanged work. Retry only when a typed result says no external
effect was attempted; never replay an ambiguous submit or cancel. Capability
means expressibility, not live software, storage, SSH, scheduler, or queue
health.

## Review

Use `ts_subagent_review` for an independent assessment of one target Claim.
Review is the only child model session. It receives a bounded graph snapshot,
one result tool, and no parent transcript, Skill, filesystem, compute, mutation,
or recursive delegation.

After success, call `ts_review_disposition` once before further scientific
mutation. Advice changes science only through normal verified Decisions.
Preserve provider failures as provider failures.

## Render, Report, And Notify

`ts_render` creates one Act-owned no-overwrite visualization; `ts_report`
creates one atomic package. Both use logical artifacts.

Use `ts_notify_user` only for configured material events. The host owns the
recipient and credentials; text cannot redirect them. Never retry ambiguous
delivery.

## Failure Boundaries

- Preserve failed Acts and calculations; operational failure does not
  contradict a Claim.
- Distinguish scheduler, transfer, program, parser, scientific, Review-provider,
  contract, artifact, and delivery failures.
- Inspect durable guards and receipts before remote recovery.
- Record verified unexpected science as Observations and/or Findings, then
  reconsider the question.

## Reference Routing

Read only the reference needed for the active decision:

| Need | Reference |
| --- | --- |
| state, identity, DAG, persistence | `references/state_model.md`, `references/pathway_model.md`, `references/workspace_contract.md` |
| Decision fields and commit discipline | `references/decision_contract.md`, `references/agent_decision_protocol.md` |
| candidates, backend choice, reflection | `references/candidate_generation.md`, `references/backend_selection.md`, `references/mechanism_reflection.md`, `references/strategy_reflection.md` |
| compute, remote, runtime failures | `references/compute_tools.md`, `references/backend_contract.md`, `references/remote_contract.md`, `references/runtime_environment.md`, `references/program_runtime_failures.md` |
| TS, connectivity, structure checks | `references/gaussian_validation.md`, `references/connectivity_validation.md`, `references/ts_structures_contract.md` |
| Review isolation and Pi context | `references/pi_agent_adapter.md` |
| render, report, notification | `references/artifact_tools.md`, `references/render_contract.md`, `references/report_template.md` |
| authored versus installed sources | `references/package_sources.md` |
