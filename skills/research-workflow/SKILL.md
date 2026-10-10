---
name: research-workflow
description: Coordinate research problems, domain Skills, durable Jobs, materials and evidence-based Results through the native Pi loop.
---

# Research loop

Read the original requirements together with later user revisions, pauses, or cancellations and the relevant Research Memory Nodes. Continue a current question or create an independent branch, choose a method, inspect execution results and revise your understanding. Use the [Research Memory Skill](../research-memory/SKILL.md) for small tool examples. A Node holds repeated attempts; a Result records a useful, immutable observation and judgment.

Register a sustained assignment with `task_begin`, using actual user submission IDs and concrete delivery criteria. `task_read` restores the user task across runs. Use `task_update` for meaningful progress, an explicit wait on Job IDs, a concrete blocker or completion evidence. A user task can span multiple Nodes and Jobs. A stage summary ends a reply, not the assignment; continue independent analysis while other branches compute. Exhausting one candidate's attempts calls for reassessing the method, not silently ending the project. Pause and cancellation are user controls.

For a compound assignment, organize independently interpretable questions with Node relations, record their local methods in plan, and bind entry/focus Nodes through `task_update` action `set_research`. The request context restores this structure alongside current evidence. A single question can stay in one Node; retries and scan points are attempts. When evidence conflicts or a route stops yielding information, compare the remaining approaches and choose an action that resolves a relevant uncertainty. Record the change and preserve the failed branch. See [planning examples](../research-memory/references/planning.md) for decomposition and revisiting questions.

Use applicable domain Skills for scientific methods. When a Skill or helper is missing, use justified methods and task scripts, making assumptions explicit and validating the approach; the catalog is not a capability allowlist. Native Pi read/write/edit/bash tools prepare inputs, analysis and reports. `job_start` owns managed scientific calculations; pass the intended node_id explicitly when associating research. Do not silently choose the most recently seen Node. Preparation and diagnostics may be unassociated. `job_collect` publishes materials and execution receipts.

Process success is not scientific validity. Inspect convergence, geometry, frequencies, connectivity and method limitations as appropriate. Use research_update for explanations and plans, research_result for independently useful conclusions with cited evidence. Failures and uncertainty are legitimate records.

Before repeating a submission, inspect its Job receipt. Reconcile uncertain dispatch with the existing identity; changed inputs for a new scientific attempt require a new submission. Monitor next_run preserves an execution event until the owning session can receive it and restores the associated Node. It does not infer a scientific plan, require a checkpoint or wake repeatedly just because a Node is open.

On a Monitor wake, check the latest user instructions, existing conclusions, and remaining budget. An event must not restart cancelled or completed work or override a stopping condition. Keep searches and retries bounded; repeated failure without new evidence calls for a changed approach or a blocker report.

For delivery, read the installed email Skill and its configuration check. Report actual results, missing work and limitations. Retain send receipts: failure to update Memory after sending must not resend mail. Node status is not delivery authorization.

Before proposing task completion, match each delivery criterion to immutable Results or materials and identify any remaining Jobs. Partial reports and negative findings may be useful progress; only the agreed delivery scope determines completion. Node closure, notes and plan edits do not establish delivery or reset the no-progress allowance. Keep scientific records in Memory and task control in the task tools; no per-turn checkpoint is required.

- [Tools and execution](references/tools.md)
- [Exact Skill resource paths](references/skills.md)
- [Generated public contract](references/public_contract.md)
- [中文说明](SKILL.zh-CN.md)
