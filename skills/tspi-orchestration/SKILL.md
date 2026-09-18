---
name: tspi-orchestration
description: Coordinate TSPi research through the canonical ResearchMap and the shared research and compute command surfaces.
---

# TSPi Orchestration

[Chinese version](SKILL.zh-CN.md)

Use this Skill when a task changes the research plan, interprets scientific
results, or needs a current project status. `ResearchMap` is the authoritative
state for one project. It is a typed aggregate containing `ResearchPhase`,
`ResearchClaim`, `ResearchNode`, `Finding`, and `Gate` objects, plus claim
relations, focus, and revision metadata. TS Web and Root read this same map
serialization directly.

The Research Kernel owns map validation, references, revisions, and atomic
changes. It does not select scientific methods or run software. Compute
environments, Attempts, and Artifacts are runtime records used by Nodes, not a
second research-state model.

## Research Loop

1. Read the current map with `ts_state mode=summary` or `mode=map`. Use
   `mode=detail`, `mode=locate`, `mode=artifacts`, `mode=capabilities`, or
   `mode=runs` only when the question needs that detail. `/research` exposes the
   same reads; `/compute` and `ts_environment` inspect local and remote compute
   environments.
2. State one research question and its uncertainty. Create or reuse a Phase,
   Claim, and bounded Node. A Phase groups Nodes for navigation; it is
   not a lifecycle state. Node state is `planned`, `active`, `paused`,
   `blocked`, or `closed`, with a closed outcome of `completed`, `inconclusive`,
   or `stopped`.
3. Load the focused domain Skill, choose a bounded method, and run it under the
   owning Node. Bind calculations and generated files to logical Artifact IDs.
4. Inspect primary outputs before writing conclusions. A Node produces
   `FactFinding` records for verified facts and `IssueFinding` records for
   anomalies, limitations, conflicts, or unresolved questions. Findings are
   part of the map; raw logs are not.
5. Add a `Gate` only when an explicit completion or claim-evaluation criterion
   is useful. Set `scope=node` for a NodeGate or `scope=claim` for a ClaimGate,
   then append an evaluation with `pass`, `fail`, `inconclusive`, or `blocked`.
6. Update Claim status (`proposed`, `supported`, `contradicted`,
   `inconclusive`, or `withdrawn`) and Node state only after the evidence and
   open issues have been considered. A NodeGate must pass before a Node can be
   closed as `completed`.

## Canonical Writes

All map mutations go through `ts_change`. Query `ts_state mode=operations` for
the live operation catalog and use the fields shown there. The current small
operation set is:

```text
create_phase       create_claim       create_node
create_finding     create_gate        evaluate_gate
set_node_state     set_claim_status   relate_claims
set_focus
```

Each operation is explicit and belongs to one `ChangeSet`. Use IDs returned by
the map or allocate a new project-local ID for a new object; never guess an
existing ID. Include a concise rationale, `expected_revision` when a stale
write would be unsafe, and source references in `basis_refs` when available.
The Kernel validates a detached copy and commits one new map revision, so a
failed change cannot leave a partial map.

Keep the model small: use only FactFinding and IssueFinding for Node outputs,
and Gate criteria/evaluations for bounded review. Do not introduce a second
evidence protocol. A calculation or Review result becomes
research state only when Root records it through `ts_change`.

## Compute And Recovery

Use `ts_state mode=capabilities capabilityKind=compute` before selecting a
calculation, and `capabilityKind=analysis` for registered analysis operations.
Use `ts_state mode=artifacts` to resolve Node-owned files and `mode=runs` to
inspect durable execution history. `ts_environment` (or `/compute`) covers
both local and remote profiles; remote is an environment kind, not a separate
public API. Treat scheduler, transfer, program, parser, and collection errors
as operational evidence. Record a scientific consequence as an IssueFinding
only after checking the primary output.

`ts_review` is advisory. Read its dossier, answer with `ts_reply`, and record
the Root interpretation in the map with `ts_change`. Preserve failed or inconclusive
Nodes and start a dependent Node when the question or deliverable changes.

## Reference Routing

Read only the reference needed for the active task:

| Need | Reference |
| --- | --- |
| vocabulary | [glossary.md](references/glossary.md), [glossary.zh-CN.md](references/glossary.zh-CN.md) |
| map model and persistence | [state_model.md](references/state_model.md), [workspace_contract.md](references/workspace_contract.md), [pathway_model.md](references/pathway_model.md) |
| ChangeSet fields and commit rules | [decision_contract.md](references/decision_contract.md), [agent_decision_protocol.md](references/agent_decision_protocol.md) |
| calculation and analysis tools | [compute_tools.md](references/compute_tools.md), [artifact_tools.md](references/artifact_tools.md), [backend_contract.md](references/backend_contract.md) |
| environments and failures | [remote_contract.md](references/remote_contract.md), [runtime_environment.md](references/runtime_environment.md), [program_runtime_failures.md](references/program_runtime_failures.md) |
| Root/Pi integration | [pi_agent_adapter.md](references/pi_agent_adapter.md) |
| package source policy | [package_sources.md](references/package_sources.md) |
| rendering | [render contract](../tspi-render/references/render_contract.md) |
| reports | [report template](../tspi-report/references/report_template.md) |
| notifications | [email delivery](../tspi-email/references/email_delivery.md) |

Use the focused Skills for transition-state search, xTB/CREST, Gaussian,
connectivity, mechanism analysis, rendering, reporting, and email delivery.
