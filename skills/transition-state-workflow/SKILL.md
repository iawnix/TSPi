---
name: transition-state-workflow
description: Auditable TS and reaction-path research in TSPi. Use for candidates, optimization/frequency/IRC, mechanisms, connectivity, xTB/CREST/ASE/Gaussian, branching, recovery, or v5 continuation.
---

# Transition-State Workflow

Root reasons about chemistry; deterministic code owns graph identity, state,
effects, provenance, and validation.

## Non-Negotiable Boundaries

- Mutate canonical science only through `ts_workspace_decision_apply`.
- Root chooses questions, hypotheses, methods, branches, stopping, and
  interpretation. Graph edges and validation never choose the next action.
- Treat Claim relations, Node dependencies, and tags as recorded context only.
- Tool results stay operational until verified artifacts support Observations.
- Record anomalies, conflicts, limitations, and unresolved questions as
  Findings. Never hide an acceptance blocker in prose.
- Freeze GateSpecs before evaluation. Review, UI, reports, and historical
  acceptance records remain read-only or advisory.

## Operating Loop

1. Read `frontier`, or `delta` when both prior revisions are known.
2. State one unresolved question, assumptions, predictions, and falsifiers.
3. Create or reuse a ResearchPhase, create/update Claims, and start one bounded
   ResearchNode with dependencies and Claim scope.
4. Select a method from chemistry, uncertainty, cost, and available artifacts.
5. Run bounded tools with the owning Node; its `node_refs` bind the journal.
6. Verify local primary outputs; record semantic Observations and Findings.
7. Freeze and evaluate GateSpecs over explicit Observation refs.
8. Update Claims; complete the Node after control checks; accept through a
   passing named profile only.
9. Recompile context and choose the next question, branch, merge, backtrack,
   stop, or completion.

One Node owns one principal question and deliverable. Same-objective retries stay
Attempts; a changed objective or principal deliverable starts a dependent Node.

Backtrack with a new Node depending on an earlier checkpoint; never erase
history. Canonical records use readable workspace ordinals (`node_1`, `claim_1`,
`obs_1`, `fnd_1`, `gsp_1`, `val_1`); ordinals are identity, not Phase or rank.

Do not impose a universal low-cost-, Gaussian-, or QST-first sequence. Gaussian
may generate candidates when justified. Before QST2/QST3, require compatible
endpoints, mapping, conformations, and an elementary-step rationale.

## Decisions

Use the control tools in this order:

1. `ts_workspace_context` for the current bounded projection.
2. `ts_workspace_decision_draft` for Root-authored operations and local aliases.
3. `ts_workspace_decision_validate` for a complete non-mutating dry run.
4. `ts_workspace_decision_apply` for the locked transactional commit.

The draft allocates IDs and resolves `$alias`. Never invent IDs or edit its
Decision; any change requires a new draft. Operations do not prescribe order.

## Validation

Use `mode=validation_capabilities` to discover predicates, templates, and
acceptance profiles. Use a versioned template or registered predicates only.

Before a template GateSpec, query its exact `templateId` and `templateVersion`;
the focused result lists parameters and Observation selectors.

The compiler freezes template, registry, content, and Observation digests. Only
`pass` satisfies a GateSpec. Agent code is forbidden. Acceptance requires
current passing coverage and no applicable open blocking Finding.

## Compute

Use context `mode=locate` to map a Claim/Node/Observation/Attempt to paths. Before
`launch`, read `mode=artifacts` and bind each `artifactId` to its `inputRole`.
`ts_subagent_compute` runs one host-bound `launch`, `inspect`, `finalize`, or
`cancel` lifecycle. The host owns identities, paths, arguments, and bindings.

If no input exists, start a Node; use `ts_structure_seed` for one SMILES or
`ts_artifact_import` for bounded Gaussian/XYZ/control text. Pass its
`artifactId`, never a path.

Do not poll unchanged work. Retry only when a typed result proves no external
effect; never replay ambiguous submit or cancel. Capability means
expressibility, not live infrastructure health.

## Review

`ts_subagent_review` independently assesses one Claim from a bounded graph and
one logical artifact batch, without parent transcript, Skill, raw filesystem,
compute, mutation, or delegation. Compute gets a fixed plan and no scientific
or method authority.

After success, call `ts_review_disposition` before scientific mutation. Apply
advice only through verified Decisions, and preserve provider failures as such.

## Artifacts, Render, Report, And Notify

`ts_render` creates one Node-owned no-overwrite visualization; `ts_report`
creates one atomic package. Both use logical artifacts.

Use `ts_notify_user` only for configured material events. The host owns the
recipient and credentials; text cannot redirect them. Never retry ambiguous
delivery.

## Failure Boundaries

- Preserve failed Nodes and calculations; operational failure does not
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
