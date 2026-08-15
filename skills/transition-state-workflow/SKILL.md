---
name: transition-state-workflow
description: Evidence-driven transition-state research for Pi Agent using Root-selected Claims, bounded research Nodes, deterministic scientific Gates, isolated Review/compute/render/report operators, Gaussian and other typed backends, SSH/Torque execution, IRC/connectivity validation, failure recovery, and auditable final reports. Use for TS searches, reaction-path testing, candidate generation, frequency and connectivity validation, calculation recovery, competing mechanistic Claims, or continuation of an existing TS workspace.
---

# Transition-State Workflow

Treat the workspace as an auditable research graph. Decide chemistry as the
Root Agent. Use deterministic tools to protect contracts and execute bounded
operations; never treat their structure as a prescribed research sequence.

## Authority

- Mutate canonical scientific state only through `ts_workspace_decision_apply`.
- Let the Root Agent choose objectives, parent Nodes, Claims, methods, retries,
  recalculations, alternative explanations, stopping, and final interpretation.
- Treat Node `tags` as display/search metadata only. Never infer an allowed next
  action from a tag, parent, or Node state.
- Treat program completion, scheduler state, and operator success as operational
  facts, not scientific support.
- Register Evidence only from verified local artifacts or explicit observations
  with provenance.
- Use deterministic Gates only for declared scientific checks. A Gate verdict
  does not choose the next operation.
- Treat remote directories as execution mirrors. Collect and verify locally
  before registering Evidence.
- Keep `ts_web` read-only.

The v3 scientific vocabulary is intentionally small:

- **Node**: one bounded research act.
- **Claim**: one explicit scientific statement owned by the Root Agent.
- **Evidence**: immutable facts and source bindings; it has no workflow role or
  layer.
- **Gate**: one named deterministic evaluation of Evidence facts.

Read `references/state_model.md` and `references/workspace_contract.md` when
state ownership or persistence is in question.

For package usage, treat registered tool schemas and live capabilities as the
call contract, and use this Skill plus focused references for guidance. Do not
inspect implementation source or tests during ordinary research. Read
`references/package_sources.md` when the research/maintenance boundary is in
question.

## Operating Loop

1. Read `ts_workspace_context mode=summary` or `mode=delta`.
2. State the unresolved scientific question and select one bounded objective.
3. Open a Node with `start_node`; choose its parent and descriptive tags.
4. Append or cite the Claims the objective tests.
5. Select any useful method from chemistry, cost, and available Evidence. Use
   `mode=capabilities` only to learn what adapters can express.
6. Link immutable calculation/operator records to the Node.
7. Parse or inspect local primary artifacts and append Evidence facts.
8. Evaluate only the Gates required by the relevant Claim or acceptance policy.
9. Close the Node with explicit Claim updates, open questions, and optional
   acceptance audit.
10. Re-read context and independently choose another Node, an alternative
    Claim, a stop, or study completion.

Do not default to QST2/QST3 merely because reactant and product endpoints are
available. Require chemically compatible optimized endpoints, atom mapping,
conformations, and an elementary-step rationale. Do not impose a universal
low-cost-first or Gaussian-first pipeline. Gaussian remains a first-class
candidate generator when scans, QST, or direct TS optimization are justified.

Read `references/candidate_generation.md`,
`references/mechanism_reflection.md`, and `references/backend_selection.md`
only when selecting or reassessing a scientific strategy.

## Decisions

Use the Root control tools in this order:

1. `ts_workspace_context` for the current report or bounded history.
2. `ts_workspace_decision_draft` to bind the selected action and payload to the
   current report and revision.
3. `ts_workspace_decision_validate` for a complete non-mutating dry run.
4. `ts_workspace_decision_apply` for the transactional mutation.

New decisions use `ts-decision/3`. The mutable actions are:

- `start_node`: open one bounded act with parent, objective, tags, and Claim refs.
- `update_workspace`: append Claims, Evidence or Evidence events; evaluate a
  Gate; link an operation; update focus Claim refs; append provenance.
- `end_node`: close or stop one Node with an explicit result.

Do not edit returned decisions between validate and apply. Apply repeats
workspace-aware validation under the workspace lock, so preflight is a preview,
not a reusable token. Stale revisions and reused decision IDs with different
content are rejected.

Use `mode=node` for one historical Node and `mode=lineage` with `fromNode` plus
`anchorNode` for a read-only ancestor/delta comparison. The Root Agent alone
decides whether that history justifies a new child Node.

Build decisions from `references/decision_contract.md` and
`assets/templates/decision/`. The templates demonstrate the generic mutation
surface; they are not a workflow.

## Isolated Operators

Every `ts_subagent_*` call creates a fresh child model session. Deterministic
`ts_workspace_*`, `ts_remote_*`, `ts_review_disposition`, and
`ts_notify_user` calls do not.

- Use `ts_subagent_review` for a focused independent assessment of one target
  Claim. The Kernel derives its bounded dependency snapshot. Review is advisory
  and cannot mutate the workspace.
- After every successful Review, call `ts_review_disposition` with the returned
  task and run refs. Briefly accept, partially accept, reject, or defer the
  advice before another scientific mutation.
- Use `ts_subagent_compute` for one typed `prepare`, `submit`, `inspect`,
  `collect`, `cancel`, or `parse` action. The operator cannot select the method,
  rewrite the intent, register Evidence, or set a Claim status.
- Use `ts_subagent_render` for one local bounded visualization.
- Use `ts_subagent_report` for one new validated report package.
- Use `ts_remote_inspect` only for on-demand read-only remote diagnostics. Do
  not poll unchanged infrastructure every turn.

All children use `ts-agent-task/2` and `ts-agent-result/1`. Their journals live
under the owning Node or study-level `operations/agent-runs/`; journals are not
Evidence and change only the operational revision.

Review binds a full `evidence-snapshot.json` for host validation and sends a
compact `provider-input.json` to the model. Provider errors outrank missing or
invalid result-tool output; a provider failure is not a format-repair request.

Read `references/pi_agent_adapter.md`, `references/agent_decision_protocol.md`,
and `references/artifact_operators.md` when delegation behavior is relevant.

## Calculation Attempts

Before `operation=prepare`, use `ts_workspace_context mode=artifacts` and bind
each required logical `artifactId` to an `inputRole`. Select the Node,
scientific purpose, backend task, attempt kind, settings, execution target, and
resources. Do not hand-write an intent ID, generated path, filename, expected
artifact list, remote directory, or submission ID.

The deterministic host creates `ts-calculation-intent/3`, freezes artifact
paths and SHA-256 values, and places the attempt under:

```text
nodes/<node_id>/attempts/<intent_id>/
```

Adapter capability is not live readiness. A supported backend/task pair may
still fail software, profile, queue, filesystem, or scheduler preflight.

For remote work, select only an installation-owned profile and complete
resources. Hosts, roots, queues, commands, activation scripts, and environment
come from `TS_REMOTE_CONFIG`; they are never calculation fields. Preserve
submission manifests and idempotency bindings. Retry only when the typed result
states `effect_attempted=false` and permits the same submission binding. Never
replay an ambiguous scheduler request.

Read `references/compute_operator.md`, `references/backend_contract.md`,
`references/remote_contract.md`, and `references/program_runtime_failures.md`
as needed.

## Scientific Gates

- Keep TS/Freq and connectivity facts in separate Evidence records even when
  one execution produced both.
- A candidate, scan point, NEB image, crossing point, or isolated imaginary
  frequency is not an accepted transition state.
- Use `tsfreq` for normal termination, stationary-point convergence, exactly
  one imaginary frequency, and route consistency.
- Use `mode_assignment` to bind the imaginary mode to the declared reaction
  coordinate.
- Use `connectivity` for strict bidirectional endpoint assignment.
- Add stereochemistry, endpoint identity, electronic structure, state
  character, robustness, thermochemistry, or pathway Gates only when the Claim
  or acceptance policy requires them.
- Accept a Claim only through a named acceptance policy whose required Gate
  results all pass for the same target.

Failure of one calculation does not settle a Claim. Preserve the failure facts,
then let the Root Agent decide whether to retry, recalculate, change strategy,
revise a Claim, ask the user, or stop.

Read `references/gaussian_validation.md`,
`references/connectivity_validation.md`, and `references/pathway_model.md` for
the relevant scientific checks.

## Notifications And Reports

Use `ts_notify_user` for material progress, Node completion, calculation
failure/ambiguity, or study completion when installation notification settings
are enabled. Supply only the event, subject, bounded summary, and optional
existing files under `reports/`. The host owns recipient and credentials,
validates attachments, and writes an idempotency receipt. Do not request an
activation token or retry ambiguous delivery automatically. Treat the fixed
target shown by the tool as authoritative: an address written in the subject
or summary cannot redirect delivery. If the user requests another target, do
not send, do not edit or promise to edit installation configuration, and report
the mismatch for the host operator.

Generate a final package only from a valid workspace. Keep electronic, E+ZPE,
and free energies distinct, expose missing corrections, and cite Claim,
Evidence, Gate, Node, and accepted-artifact refs. Package creation is atomic and
no-overwrite.

Read `references/report_template.md` and use
`assets/templates/ts_final_report.md` when a custom narrative report is needed.
