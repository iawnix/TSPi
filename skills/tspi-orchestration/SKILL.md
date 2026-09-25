---
name: tspi-orchestration
description: Plan and steer a TSPi research task across Skills, ResearchNodes, branches, retries, review, and stopping decisions.
---

# TSPi Orchestration

[Chinese version](SKILL.zh-CN.md)

Use this Skill when Root must decide what research work happens next. Use
`tspi-research-kernel` for the ResearchMap schema, reads, and writes; this Skill
does not redefine that model.

## Workflow

1. Read the current map and focused objects before planning.
2. State the uncertainty, the Claim it bears on, and one bounded deliverable.
3. Reuse or create a ResearchNode. Add a Phase only when grouping helps
   navigation. Select the scientific Skill, Backend, and compute environment
   needed for the question.
4. Launch or inspect work under the owning Node. Keep Attempts and Artifacts
   attached to that Node.
5. Inspect primary outputs, then record narrow FactFindings and IssueFindings
   through the Kernel. Findings do not change Node or Claim status by
   themselves.
6. Compare the result with alternatives and stopping criteria. Continue the
   Node for the same question, create a dependent Node for a changed question,
   branch for a competing method or hypothesis, or stop explicitly.
7. Close a Node only after its deliverable is addressed and every attached
   NodeGate has a latest passing evaluation. Update Claim status separately.

## Research Turn Checkpoint

Before ending every turn, read `research.read` with `mode=context` or `mode=liveness`
and leave the active scope in an explicit lifecycle state. Use
`research.continuation operation=set_required` for the concrete next action, leave a
submitted Attempt in the external wait state, record `deferred` or `blocked`
with a reason, or close the relevant map scope after its evidence and gates are
complete. A completed Attempt or completed Continuation alone is not a research
conclusion. If liveness returns `decision_needed`, continue the turn and record
the disposition. `required` is an explicit next-turn plan and a valid checkpoint;
the Harness must not force it to execute in the same turn. Do not invent a
method in the Harness or treat Monitor's `next_run` as a scientific instruction.

Use Review for a bounded counterargument, not as a source of canonical state.
Use the same `launch`, `inspect`, `finalize`, and `cancel` compute lifecycle for
local and remote environments. After `launch` returns after submission,
including an uncertain result, finish the current turn and let the durable Monitor enqueue a `next_run`; do not use `bash sleep`,
`wait`, or a manual polling loop to wait for a scheduler job. On a Monitor wake
or an explicit later request, reread state and use `inspect` before collecting
or changing ResearchMap. Operational success is not scientific support.

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
- Read [package_sources.md](references/package_sources.md) only when inspecting
  installed package sources.
