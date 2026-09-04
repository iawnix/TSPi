---
name: transition-state-workflow
description: Auditable TSPi research for TS candidates, opt/freq/IRC, mechanisms, connectivity, branching, recovery, and continuation.
---

# Transition-State Workflow

Root reasons about chemistry; deterministic code owns graph identity, state,
effects, provenance, and validation.

## Non-Negotiable Boundaries

- Mutate canonical science only through `ts_change`.
- Root chooses questions, hypotheses, methods, branches, stopping, and
  interpretation. Graph edges and validation never choose the next action.
- Treat Claim relations, Node dependencies, and tags as recorded context only.
- Tool results stay operational until verified artifacts support Observations.
- Record anomalies, conflicts, limitations, and unresolved questions as
  Findings. Never hide an acceptance blocker in prose.
- Freeze ProofSpecs before evaluation. Review, UI, reports, and historical
  acceptance records remain read-only or advisory.

## Operating Loop

1. Read `frontier`, or `delta` when both prior revisions are known.
2. State one unresolved question, assumptions, predictions, and falsifiers.
3. Create or reuse a ResearchPhase and start one decision-sized ResearchNode
   with dependencies and Claim scope. When that Node is the active work item,
   include `set_focus` in the same Decision (or immediately after it) using
   the exact `claimRefs`/`nodeRefs` contract; preserve an existing focus only
   when that is intentional and stated in the rationale.
4. Select a method from chemistry, uncertainty, cost, and available artifacts.
5. Run bounded tools with the owning Node; its `node_refs` bind the journal.
6. Inspect parser candidates, verify local primary outputs, and use `ts_change`
   to promote selected values into semantic Observations and Findings.
7. Freeze and evaluate ProofSpecs over explicit Observation refs.
8. After every owned Attempt is stable and interpreted as needed, update Claims
   and complete the Node as soon as its one question is answered.
9. Recompile context; record the next material decision as a dependent Node or
   a new Phase, or explicitly stop. Accept through a passing profile only.

One Node is one visible decision. New questions or deliverables start dependent
Nodes; retries stay Attempts. One Decision may close its new Node, or a prior
Node while opening one dependent successor. See
`references/agent_decision_protocol.md` for the boundary test.

Backtrack with a new Node depending on an earlier checkpoint; never erase
history. Canonical records use readable workspace ordinals (`node_1`, `claim_1`,
`obs_1`, `fnd_1`, `proof_1`, `result_1`); ordinals are identity, not Phase or rank.

Do not impose a universal backend or search sequence.

## State And Change

Use `ts_state` for bounded reads and `ts_change` for one Root-authored atomic
change using local aliases.

Before using an unfamiliar change operation, query
`ts_state mode=change_contract operation=<op>` and follow its exact fields. Do
not infer a field from another operation.

The Kernel owns IDs, `$alias` resolution, validation, and atomic commit. Never
invent IDs, paths, receipts, or generated Decisions.

## Validation

Use `ts_state mode=capabilities capabilityKind=proof`; bind an exact versioned
template or registered predicates only.

The compiler freezes template, registry, content, and Observation digests. Only
`pass` satisfies a ProofSpec. Agent code is forbidden. Acceptance requires
current passing coverage and no applicable open blocking Finding.

## Compute

Use context `mode=locate` to map a Claim/Node/Observation/Attempt to paths. Before
`launch`, read `mode=artifacts` and bind each `artifactId` to its `inputRole`.
`ts_calc` runs one host-bound `launch`, `inspect`, `finalize`, or
`cancel` lifecycle. The host owns identities, paths, arguments, and bindings.
Non-primary launch cites a same-Node `sourceAttempt`. Retry unchanged bindings,
recalculate changed bindings; a new question starts a Node.

If no input exists, start a Node; use `ts_seed` for one SMILES or
`ts_import` for bounded Gaussian/XYZ/control text. Pass its
`artifactId`, never a path.

Do not poll unchanged work. Retry only when a typed result proves no external
effect; never replay ambiguous submit or cancel. Capability means
expressibility, not live infrastructure health.

Keep the owning Node open through interpretation. Remote `completed` still
requires finalize; any unsettled or invalid Attempt blocks Node completion.

## Review

`ts_review` independently assesses one Claim from a bounded graph and
one logical artifact batch, without parent transcript, Skill, raw filesystem,
compute, mutation, or delegation. Compute gets a fixed plan and no scientific
or method authority.

After success, call `ts_reply` before scientific mutation. Apply advice only
through verified `ts_change` requests, and preserve provider failures as such.

## Artifacts, Render, Report, And Notify

Compare, render, and report outputs stay operational until `ts_change` records
verified facts. All use logical artifacts.

Use `ts_notify` only for configured material events. The host owns the
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
