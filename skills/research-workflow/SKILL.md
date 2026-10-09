---
name: research-workflow
description: Coordinate research problems, domain Skills, durable Jobs, materials and evidence-based Results through the native Pi loop.
---

# Research loop

Read the original requirements together with later user revisions, pauses, or cancellations and the relevant Research Memory Nodes. Continue a current question or create an independent branch, choose a method, inspect execution results and revise your understanding. Use the [Research Memory Skill](../research-memory/SKILL.md) for small tool examples. A Node holds repeated attempts; a Result records a useful, immutable observation and judgment.

Use applicable domain Skills for scientific methods. When a Skill or helper is missing, use justified methods and task scripts, making assumptions explicit and validating the approach; the catalog is not a capability allowlist. Native Pi read/write/edit/bash tools prepare inputs, analysis and reports. `job_start` owns managed scientific calculations; pass the intended node_id explicitly when associating research. Do not silently choose the most recently seen Node. Preparation and diagnostics may be unassociated. `job_collect` publishes materials and execution receipts.

Process success is not scientific validity. Inspect convergence, geometry, frequencies, connectivity and method limitations as appropriate. Use research_update for explanations and plans, research_result for independently useful conclusions with cited evidence. Failures and uncertainty are legitimate records.

Before repeating a submission, inspect its Job receipt. Reconcile uncertain dispatch with the existing identity; changed inputs for a new scientific attempt require a new submission. Monitor next_run preserves an execution event until the owning session can receive it and restores the associated Node. It does not infer a scientific plan, require a checkpoint or wake repeatedly just because a Node is open.

On a Monitor wake, check the latest user instructions, existing conclusions, and remaining budget. An event must not restart cancelled or completed work or override a stopping condition. Keep searches and retries bounded; repeated failure without new evidence calls for a changed approach or a blocker report.

For delivery, read the installed email Skill and its configuration check. Report actual results, missing work and limitations. Retain send receipts: failure to update Memory after sending must not resend mail. Node status is not delivery authorization.

- [Tools and execution](references/tools.md)
- [Exact Skill resource paths](references/skills.md)
- [Generated public contract](references/public_contract.md)
- [中文说明](SKILL.zh-CN.md)
