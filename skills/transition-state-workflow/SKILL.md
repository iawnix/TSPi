---
name: transition-state-workflow
description: Auditable transition-state and reaction-path research in TSPi using a Root-owned Claim graph, ResearchAct DAG, deterministic Compute/Render/Report tools, semantic Observations, declarative GateSpecs, isolated advisory Review, SSH/Torque execution, connectivity validation, failure recovery, and reproducible reports. Use for TS candidate generation, optimization/frequency/IRC studies, mechanism alternatives, pathway validation, xTB/CREST/ASE/Gaussian calculations, scientific backtracking, or continuation of a v4 TS workspace.
---

# Transition-State Workflow

Treat the workspace as an auditable research graph. Reason about chemistry as
the Root Agent. Use deterministic tools for state integrity and bounded effects;
never treat graph structure or validation templates as a prescribed workflow.

## Authority

- Mutate canonical science only through `ts_workspace_decision_apply`.
- Choose questions, hypotheses, methods, alternatives, dependencies,
  backtracking, retries, stopping, and interpretation as the Root Agent.
- Treat Claim relations, Act dependencies, and tags as recorded context only.
  Never infer a permitted next action from them.
- Treat program, scheduler, parser, render, report, and notification status as
  operational facts until verified artifacts support semantic Observations.
- Record Observations only from verified local artifacts or explicit
  user-provided facts with provenance and exact artifact digests.
- Record anomalies, conflicts, limitations, and unresolved questions as
  Findings; do not hide blockers in prose.
- Freeze a GateSpec before evaluating selected Observations. A validation
  verdict constrains a Claim but does not choose the next Act.
- Treat remote directories as execution mirrors. Collect and verify locally.
- Keep `ts_web`, UI activity, and Review advisory.

Read [state_model.md](references/state_model.md) and
[workspace_contract.md](references/workspace_contract.md) when ownership,
identity, persistence, or DAG semantics are in question. Read
[package_sources.md](references/package_sources.md) when deciding whether a
source belongs to research use or package maintenance.

## Operating Loop

1. Read `ts_workspace_context mode=frontier` or a revision-bound `mode=delta`.
2. State one unresolved scientific question and its possible falsifiers.
3. Create or update explicit Claims, then start one bounded ResearchAct with
   only scientifically meaningful dependencies.
4. Select a method from chemistry, cost, current uncertainty, and available
   artifacts. Capability catalogs show expressibility, not strategy or health.
5. Run deterministic tools and link their immutable operation records to the
   Act.
6. Verify local primary outputs. Record semantic Observations and any Findings.
7. Freeze relevant GateSpecs, then evaluate them over explicit Observation
   refs. Never weaken a frozen specification after seeing a result.
8. Update Claims with cited Observations/results, complete the Act, and create
   an acceptance record only when a named profile passes.
9. Recompile context and independently choose a branch, merge, backtrack, new
   question, explicit stop, or completion.

The ResearchAct DAG preserves history and supports multiple dependencies. To
backtrack, start a new Act that depends on the earlier checkpoint; do not erase
failed or superseded work. Claim relations separately preserve refinement,
dependency, conflict, and alternative scientific interpretations.

Do not impose a universal low-cost-first, Gaussian-first, or QST-first sequence.
Gaussian is a first-class candidate generator when direct TS optimization,
scans, or QST are chemically justified. Require compatible endpoints, atom
mapping, conformations, and an elementary-step rationale before QST2/QST3.

Read [candidate_generation.md](references/candidate_generation.md),
[backend_selection.md](references/backend_selection.md), and
[mechanism_reflection.md](references/mechanism_reflection.md) when choosing an
initial strategy. Read [strategy_reflection.md](references/strategy_reflection.md)
when repeated results require reassessment.

## Decisions

Use the control tools in order:

1. `ts_workspace_context` for the current bounded projection.
2. `ts_workspace_decision_draft` for Root-authored v4 operations and local
   aliases.
3. `ts_workspace_decision_validate` for a complete non-mutating post-state
   dry run.
4. `ts_workspace_decision_apply` for the locked transactional commit.

The draft allocates all technical IDs and resolves `$alias` references. Do not
invent `dec_`, `clm_`, `rel_`, `act_`, `obs_`, `fnd_`, `gsp_`, `val_`, or
`acc_` IDs. Do not edit the returned `ts-research-decision/1`; any change needs
a new draft.

Available draft primitives are:

```text
create_claim            relate_claims
start_act               complete_act
record_observation      record_finding      resolve_finding
freeze_validation_spec evaluate_validation
update_claim            accept_claim
set_focus               link_operation
```

These primitives can be combined in one ordered Decision and are not a required
sequence. Build them from [decision_contract.md](references/decision_contract.md)
and `assets/templates/decision/`. Follow
[agent_decision_protocol.md](references/agent_decision_protocol.md) for
backtracking, Review response, and acceptance discipline.

## Validation

Use `ts_workspace_context mode=validation_capabilities` to discover registered
predicates, templates, and acceptance profiles. Choose either:

- a packaged versioned template plus typed parameters; or
- a declarative definition composed only of registered predicates.

The compiler fully expands and freezes the GateSpec with template, predicate
registry, and content digests. The evaluator binds selected Observation
digests and returns `pass`, `fail`, `inconclusive`, or `error`. Do not treat the
last two as pass.

The Agent cannot provide Python, shell, imports, expressions, or executable
plugins. Add new scientific dimensions through maintained templates and
predicates, not fixed workflow branches. Before accepting a Claim, require the
profile's dimensions, a supported Claim, at least one attached GateSpec, the
latest passing result for every attached GateSpec, current digests, and no
applicable open blocking Finding. Treat an older acceptance as history when its
Claim, latest validation, or relevant Finding snapshot has changed.

Read [gaussian_validation.md](references/gaussian_validation.md),
[connectivity_validation.md](references/connectivity_validation.md), and
[pathway_model.md](references/pathway_model.md) for common scientific checks.
Read [ts_structures_contract.md](references/ts_structures_contract.md) for atom
maps, alignment, stereochemistry, and endpoint identity.

## Compute

Before `operation=prepare`, read
`ts_workspace_context mode=artifacts` and bind required logical `artifactId`
values to `inputRole` values. Select the owning `actId`, purpose, backend task,
attempt kind, settings, execution target, and resources. The host creates the
intent ID, paths, filenames, expected artifacts, remote directory, and
submission binding.

Use `ts_compute` for exactly one deterministic operation:

- `prepare`: freeze `ts-calculation-intent/4` and generated inputs;
- `submit`: stage and submit the bound remote intent;
- `inspect`: reconcile changed or terminal state and optionally tail a declared
  artifact;
- `collect`: download declared artifacts through the immutable manifest;
- `parse`: parse one local bound artifact;
- `cancel`: cancel only the bound intent.

Do not poll unchanged work every turn. Retry only when the typed result states
that no external effect was attempted and retry is allowed. Never replay an
ambiguous submit or cancel. A supported backend/task pair does not prove live
software, storage, SSH, Torque, or queue health.

Read [compute_tools.md](references/compute_tools.md),
[backend_contract.md](references/backend_contract.md),
[remote_contract.md](references/remote_contract.md), and
[program_runtime_failures.md](references/program_runtime_failures.md) as needed.

## Review

Use `ts_subagent_review` for an independent assessment of one target Claim.
Review is the only child model session. It receives a bounded graph snapshot,
one result tool, no parent conversation, no package Skill, no filesystem,
no compute, no mutation, and no recursive delegation.

Review output is advisory. After every successful Review, call
`ts_review_disposition` exactly once with its task/run refs and briefly accept,
partially accept, reject, or defer the advice before another scientific
mutation. Even accepted advice changes science only through verified artifacts
and a normal Decision.

Provider failure is not a format error. A structural result failure may receive
one same-session repair; provider HTTP/stream failure must remain visible and
must not be rewritten as a missing result-tool call.

Read [pi_agent_adapter.md](references/pi_agent_adapter.md) for child isolation,
context delivery, journals, and UI lifecycle.

## Render, Report, And Notify

Use `ts_render` for one Act-owned no-overwrite visualization and `ts_report` for
one atomic report package from a valid workspace. Both are deterministic tools;
neither interprets chemistry or starts a child model. Use logical artifact IDs
and let the host allocate output paths.

Use `ts_notify_user` only for material configured events. The host owns the
fixed recipient and credentials. The Root supplies event, subject, bounded
summary, and optional existing files under `reports/`. Text cannot redirect the
recipient. Known delivery is idempotent; ambiguous delivery is not retried
automatically.

Read [artifact_tools.md](references/artifact_tools.md),
[render_contract.md](references/render_contract.md), and
[report_template.md](references/report_template.md). Use
`assets/templates/ts_final_report.md` only for a custom narrative; the normal
report tool renders deterministically from canonical records.

## Failure Boundaries

- Preserve calculation and Act failure records; failure is not automatically a
  contradicted Claim.
- Distinguish scheduler, transfer, program, parser, scientific, Review-provider,
  contract, render, report, and notification failures.
- Inspect durable compute guards/receipts before any remote recovery.
- Record unexpected scientific output as an Observation and/or Finding when
  verified, then decide how it changes the research question.
- Ask the user only when scientific choice, new authority, or external
  coordination is genuinely required.

Read [runtime_environment.md](references/runtime_environment.md) only for the
isolated Python runtime. Read [render_contract.md](references/render_contract.md)
only for visualization path/output rules.
