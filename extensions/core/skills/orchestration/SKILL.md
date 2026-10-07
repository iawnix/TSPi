---
name: orchestration
description: Plan and steer a TSPi research task across Skills, ResearchNodes, branches, retries, review, and stopping decisions.
---

# TSPi Orchestration

[Chinese version](SKILL.zh-CN.md)

Use this Skill when Root must decide what research work happens next. Use
`research-state` for the ResearchMap schema, reads, and writes; this Skill
does not redefine that model.

## Workflow

1. Read the current map and focused objects before planning.
2. State the uncertainty, the Claim it bears on, and one bounded deliverable.
3. Create or confirm the Claim and ResearchNode with `research_change` before referencing them. Record a `research_strategy` plan covering the focused Claim/Node before execution or evidence writes. An unknown Claim error requires creating the object, then retrying the strategy. Reuse or create a ResearchNode. Add a Phase only when grouping helps
   navigation. Read the exact scientific Skill locations listed in the system prompt. Use method-selection even when the user fixed the method: its request helper reads installation job.toml and binds the configured interpreter, executable and environment. Generic job_probe does not verify a scientific method; run the Skill’s method checks when needed.
   For a method comparison, first create the complete
   `method × environment × {opt, sp}` matrix with a method, environment,
   input Artifact, and dependency for every cell. An `sp` job may consume only
   the `opt` output from the same method and environment. Block an unavailable
   cell explicitly; do not substitute methods or stop independent cells.
4. Launch or inspect work under the owning Node. Keep Attempts and Artifacts
   attached to that Node.
5. Inspect primary outputs, then record narrow FactFindings and IssueFindings
   through the Research State. Findings do not change Node or Claim status by
   themselves.
6. Compare the result with alternatives and stopping criteria. Continue the
   Node for the same question, create a dependent Node for a changed question,
   branch for a competing method or hypothesis, or stop explicitly.
7. Close a Node only after its deliverable is addressed and every attached
   NodeGate has a latest passing evaluation. Update Claim status separately.

## Research Turn Checkpoint

Before ending every turn, read `research_read` with `mode=context` or `mode=liveness`
and close the lifecycle with `research_checkpoint`. Record strategy and Attempt
interpretation first when applicable, then use one explicit disposition:
`continue_required`, `waiting_external`, `deferred`, `blocked`, `terminal`, or
`user_input_required`. `research_checkpoint` is the canonical turn checkpoint.
A completed Attempt or lifecycle action alone is not a research conclusion.
If liveness returns `decision_needed` with no explicit disposition, record the missing strategy or checkpoint. A successful `user_input_required` checkpoint ends the turn; do not repeat it or attempt blocked writes. When liveness also reports `execution_ready=true`, an
active StrategyPlan already covers the focused scope and the planned
prepare/execute work may proceed before that checkpoint; the checkpoint is
still required before ending the turn. A `continue_required` checkpoint asks State to persist a continuation for the owning session; Host submits it through Pi after the current turn. Inspect the returned continuation decision: unchanged research revisions reuse one wake identity, and eight successive advancing checkpoints exhaust the automatic budget. Report a denied continuation rather than promise another automatic turn. Do
not invent a method in the Harness or treat Monitor's `next_run` as a
scientific instruction.

Use `job_start/job_status/job_collect` for local and remote execution. Once submitted, preserve the Job/Attempt identity; reconcile uncertain outcomes before retrying. Finish the turn with `waiting_external` when only external work remains, and let Monitor wake the owning session on a meaningful change. Independently planned ready Nodes may proceed while another Job waits. Do not poll with sleep loops.

Use `artifact_register` or `artifact_create` to preserve actual files, and `artifact_link` for evidence relations. `artifact_derive` only records a derivation descriptor; run actual analysis through a Skill Job and register its outputs. Operational success is not scientific support. Record interpretations from inspected evidence before updating scientific conclusions.

For requested email, read the listed email Skill and run its no-send `check` using installation configuration before asking for an address. Missing recipients block only delivery; keep scientific work and delivery in separate Nodes when they have different dependencies. Mark the whole active scope `user_input_required` only when no independent authorized work remains. Unverified method availability is an Agent investigation step, not information the user must supply by default.

## References

- Read [agent_decision_protocol.md](references/agent_decision_protocol.md) for
  branching, recovery, and stopping decisions.
- Read [compute_tools.md](references/compute_tools.md) and
  [artifact_tools.md](references/artifact_tools.md) for public execution and
  Artifact calls.
- Read [program_runtime_failures.md](references/program_runtime_failures.md)
  when an Attempt fails or has an unknown effect.
- Read [pi_agent_adapter.md](references/pi_agent_adapter.md) for Root tools and
  slash commands.
- Read [runtime_boundaries.md](references/runtime_boundaries.md) for Agent
  Runtime, Host/App Server, memory, Research State, Monitor, and compute ownership.
- Read [package_sources.md](references/package_sources.md) only when inspecting
  installed package sources.

## Operational observations and recovery

Routine probes stay in tool history; they need not become FactFindings. Continue
input preparation and execution after successful probes. Register an observation
as an Artifact only when it supports a decision or must be cited across turns;
then use its returned artifact_id in source_refs. Tool names and invented IDs are
not evidence. An optional Finding failure must not stop independent preparation.
Keep optional diagnostics separate from required Node updates in ChangeSets.
Required strategy/input evidence failures must still be repaired before execution.

Read [runtime boundaries](references/runtime_boundaries.md) for scoped user waits.
Prefer one Node per independently executable method/environment cell and a separate dependent delivery Node. A Node is research scope, not a process lock. If independent Jobs share a Node, preserve distinct helper-generated workId values; a running Attempt without a new work identity requires reconciliation, not another submission. Read the exact listed email Skill location; a failed
path lookup is not evidence that email or a recipient is unavailable.

- [Public contract / 公开契约](references/public_contract.md): generated tool names and dispositions.
