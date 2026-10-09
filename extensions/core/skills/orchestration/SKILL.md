---
name: orchestration
description: Plan and steer a TSPi research task, choose methods, inspect evidence, continue independent work, and decide when to stop.
---

# Research orchestration

[中文](SKILL.zh-CN.md)

Use this Skill to decide what research work to do next. The research-state Skill
explains how to preserve requirements and evidence. Domain Skills supply scientific
methods; this Skill applies equally to computational and non-computational work.

1. Compare the actual user sources with the requested deliverables. Preserve each
   obligation before choosing a plan. An unavailable method or acceptance template
   leaves an unmet requirement; it does not remove the requested work.
2. Choose a bounded next step using the current State snapshot and the relevant
   installed domain Skill. Create a Node for independently manageable work. Use
   a Claim for a scientific proposition and a StrategyPlan when alternatives,
   switching conditions or budgets need a durable explanation. Simple work needs
   neither a placeholder Claim nor a formal plan.
3. Preserve dependencies between inputs and later work. Reuse current results;
   inspect or reconcile an uncertain Attempt before submitting it again. An
   unavailable branch does not prevent independent authorized branches.
4. Perform scientific computation through Jobs with an explicit configured
   environment. Inspect and collect the resulting evidence. Read the selected
   Skill for preparation and validation; do not infer scientific availability
   from a generic scheduler or process probe.
5. Assess the requested deliverable and any attached Gate against current
   evidence. Record a Finding only when a reusable observation or issue helps the
   research. A completed calculation does not itself establish a scientific Claim.
6. Complete authorized delivery using its installed Skill. Separate a delivery
   dependency or missing recipient from independent research work. Preserve an
   existing side-effect receipt when State recording fails; recover the recording
   without repeating the effect.
7. Checkpoint the current scope before ending. Continue ready authorized work;
   use waiting_external when only external execution remains. Request user input
   only when the missing decision prevents all remaining authorized work. Report
   unfinished requirements explicitly when stopping partially.

Read the actual tool error and repair its identified prerequisite. An atomic
ChangeSet error means none of its operations committed. Keep completed work and
receipts. A failed optional diagnostic need not interrupt independent work.

## References

- [Decision procedure](references/agent_decision_protocol.md): branching and stopping.
- [Jobs](references/compute_tools.md) and [Artifacts](references/artifact_tools.md).
- [Runtime failures](references/program_runtime_failures.md): ambiguous effects and recovery.
- [Root tools](references/pi_agent_adapter.md) and [public contract](references/public_contract.md).
- [Runtime boundaries](references/runtime_boundaries.md): ownership and scoped waits.
- [Package sources](references/package_sources.md): inspecting installed resources.
