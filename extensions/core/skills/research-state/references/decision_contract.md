# Recording and revising research decisions

Use `research_change` for map changes. Query
`research_read mode=operations query=<operation>` for the authoritative fields,
constraints and examples. Use existing IDs and keep related operations in one
coherent request; later operations may refer to objects created earlier in it.
Use the current revision when the decision depends on a specific State snapshot.
A rejected batch leaves the prior map intact. Diagnose its reported operation and
repair the cause through tools rather than editing canonical files.

Record a Finding for a verified output, meaningful limitation or unresolved
scientific issue. Cite registered evidence and keep the statement no stronger
than that evidence. A plan or object ID is a decision basis, not scientific
material. Use the request's decision-basis field for such context.

Assess a Claim explicitly from inspected evidence. Literature and imported data
can support an assessment without a new calculation. An untested plan cannot.
Read `mode=decisions` for assessment reasons and evidence bindings. When evidence
or an attached Gate changes, inspect the resulting review requirement and reassess;
keep the earlier decision as history. Independent work may continue while a
conclusion awaits review, but the stale conclusion cannot justify final success.

Attach a Gate when a Node or Claim decision benefits from explicit criteria.
Ordinary Nodes need no Gate. Requirements preserve user deliverables regardless
of local Gate choices; see [requirements](requirements.md). Use runtime facts and
registered validators for checks they can establish, and explicit Agent judgment
for scientific interpretation. Explain changed criteria rather than silently
replacing them. A machine failure cannot be changed into a pass by an assessment.

Inspect collected outputs before recording an Attempt interpretation. Use the
result receipt and its direct evidence for the result of that run; distinguish
comparison and background evidence. Operational observations and execution issues
refer to Runtime observations. Correct an earlier interpretation by superseding it.
Changed outputs require a fresh decision against their current versions.

An atomic failure need not mean every proposed operation was wrong. Repair the
reported target, retain valid artifacts and side-effect receipts, and submit the
remaining coherent decision. A failure to record delivery does not authorize
sending the delivery again.
