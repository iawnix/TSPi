---
name: transition-state-workflow
description: Evidence- and hypothesis-driven transition-state research for Pi Agent, with auditable node trees, isolated calculation/review agents, Gaussian and other backend boundaries, TS/Freq and connectivity gates, recalculation lineage, read-only web views, and final reports. Use for TS searches, mechanism testing, IRC/connectivity validation, program-failure recovery, pathway audits, and continuation of an existing TS workspace.
---

# Transition-State Workflow

Use the workspace as an auditable research tree. The Root Agent decides what the
evidence means and what to do next. Tools enforce contracts and perform bounded
operations; they do not choose chemistry.

## Non-Negotiable Boundaries

- Canonical state is `research_state.json`, `hypotheses.json`, and
  `evidence_registry.json` only.
- Mutate canonical state only through `ts_workspace` decisions.
- Keep candidate, TS/Freq, connectivity, accepted-TS audit, and pathway audit
  evidence separate.
- Program success is not scientific support.
- Candidate and validation nodes return program facts and evidence only. A
  mechanism node alone may set hypothesis status.
- Remote files are execution mirrors. Collect and verify locally before using
  them as evidence.
- Cluster submission or cancellation requires explicit current-turn host
  authorization. Do not treat the bundled MCP client as standing permission.
- `ts_web` is read-only.
- Sending email requires explicit current-turn authorization.

## Node Ontology

New work uses `ts-node/2` and one `node_type`:

| `node_type` | Use |
|---|---|
| `intake` | `n000` only: normalize user inputs, structures, constraints, and completion criteria. |
| `mechanism` | Propose, compare, revise, or evaluate a falsifiable hypothesis. |
| `candidate_search` | Generate transition-state, endpoint-conformer, intermediate, or crossing-point candidates. |
| `validation` | Produce evidence for a declared prediction. |
| `audit` | Audit a TS, elementary step, pathway, or complete study. |

Validation scopes are `tsfreq`, `connectivity`, `electronic_structure`,
`state_character`, `thermochemistry`, `method_robustness`, and
`geometry_identity`.

Frequency and IRC/connectivity normally use separate validation nodes. If the
mechanism may be falsified by wavefunction analysis, open an
`electronic_structure` or `state_character` validation node, then open a
`mechanism` evaluation node to assign `supported|unsupported|ambiguous`.

Recalculation is not a node type. A technical retry is a new attempt under the
same node. A scientifically meaningful method change opens a new node of the
same scientific type with `attempt_kind=recalculation`,
`recalculation_ref`, and `branch_context.relation=recalculation_of`.

Read `docs/RESEARCH_NODE_ONTOLOGY.md` and `references/state_model.md` when node
type, scope, or status semantics are in question.

## Status Axes

Keep these independent:

- `node.lifecycle`: `running|closed|stopped`
- `closure.program.outcome`: `success|failure|not_run`
- `closure.hypothesis.status`: `supported|unsupported|ambiguous`, mechanism only
- `closure.audit.status`: `accepted|not_accepted|ambiguous`, audit only

Missing or conflicting evidence is `ambiguous`, not `unsupported`. A failed
program does not evaluate the hypothesis.

## Operating Loop

1. Read current state with `report_workspace` or `ts_workspace_context`.
2. State the active hypothesis, prediction, evidence ceiling, and unresolved
   discriminator.
3. Select one next research act and construct a `ts-decision/2`.
4. Validate the decision against the current `workspace_revision`.
5. Apply exactly one mutation.
6. Delegate bounded computation or review when useful.
7. Verify local primary artifacts and register evidence through
   `update_workspace`.
8. Close the node with only the status sections allowed for its `node_type`.
9. Use a later mechanism or audit node for interpretation.
10. Re-read the workspace before branching, backtracking, stopping, or
    reporting.

Do not default to QST2/QST3 merely because R/P endpoints are available; justify QST use
from endpoint optimization, atom mapping, conformer
compatibility, and the elementary-step model.

## Pi Control Plane

Use these four tools in order when mutating:

1. `ts_workspace_context`: `summary|delta|node|branch|audit` context.
2. `ts_workspace_decide`: non-mutating `ts-decision/2` draft.
3. `ts_workspace_validate`: workspace-aware preflight.
4. `ts_workspace_apply`: transactional mutation and refreshed compact context.

Only `ts_workspace_apply` mutates canonical state. Do not hand-edit decision or
state files between decide, validate, and apply. A stale `base_revision` is
rejected.

Pi injects only a short control-plane reminder at turn start, not the full
workspace report. Use `mode=delta` with the last scientific and operational
revisions. Load historical context only when needed:

- `mode=node, nodeId=<id>` for one checkpoint;
- `mode=branch, fromNode=<trigger>, anchorNode=<checkpoint>` before backtrack;
- `mode=audit` before acceptance or completion review.

Construct new decisions from `references/decision_contract.md`. Files under
`templates/decision/` are legacy-compatible examples; tests are fixtures, not
operating instructions.

## Hypothesis And Branch Rules

- `n000` is `node_type=intake` and has no parent.
- The initial `mechanism, mechanism_action=propose` node creates the first
  structured hypothesis.
- Later candidate, validation, audit, and mechanism-evaluation nodes cite a
  known `hypothesis_ref`.
- Every post-`n000` start decision carries `branch_context`.
- The Root Agent selects `continue_parent`, `new_solution_branch`,
  `new_hypothesis_branch`, `new_pathway_branch`, or `recalculation_of` after
  inspecting evidence and relevant history.
- Backtracking selects a historical anchor, loads its context, and creates a
  new child branch. It does not rewrite the old node.
- For `node_type=audit, audit_scope=pathway`, `payload.pathway_ref` is mandatory.
  Before closing, register and cite a pathway audit evidence record with a
  strict accepted or not-accepted decision. Audit support does not itself mean
  pathway success.

Read `references/agent_decision_protocol.md` before using previous failed
exploration to choose an anchor or branch relation.

## Isolated Agents

Use `ts_workspace_subagent` only at high-value ambiguity, failure-analysis,
backtrack, or audit boundaries. Each call creates a fresh tool-free session
with no parent history, root skills, extensions, `AGENTS.md`, or workspace
write access.

Use `ts_workspace_compute_operator` for one bound `prepare`, `submit`,
`inspect`, `collect`, `cancel`, or `parse` operation. Pass the backend selected
by the Root Agent. The child gets only request-scoped typed tools and one
private backend skill. It cannot select methods, change the intent, register
evidence, or set a scientific status. `submit` and `cancel` fail closed without
an interactive Pi UI and require a fresh host confirmation before the child is
created; no authorization field is passed to the child.

Use `ts_workspace_render_operator` for one node-owned local render,
`ts_workspace_report_operator` for one new validated report package, and
`ts_workspace_email_operator` for one local email draft from a generated report
summary. Each child gets one private role skill and one path-bound typed tool.
The email operator cannot send, access a network, select a sender, infer
addresses, or read credentials.

All isolated roles use `ts-agent-task/1` and `ts-agent-result/1`. Review,
backend, render, report, and email results are non-authoritative. Results that
contain hypothesis status, branch context, acceptance, or strict pathway
decision fields are rejected.

The Pi host journals each run under the owning node's `agent-runs/` directory,
or under `operations/agent-runs/` for study-level work. These records drive
`operational_revision`; they are not evidence and never change the scientific
`workspace_revision`.

Read `references/pi_agent_adapter.md`, `references/compute_operator.md`, and
`references/artifact_operators.md` when changing or debugging delegation.

## Calculation Attempts

Use `ts-calculation-intent/2` for new work. Declare `validation_scope`,
`attempt_kind`, `recalculation_ref`, backend, task type, inputs, expected local
artifacts, and execution target.

New attempt authority lives under:

```text
nodes/<node>/attempts/<intent>/
```

A remote target must declare `authority=execution_mirror` and selects
`transport=ssh|mcp`; omitted transport on legacy SSH targets means `ssh`. MCP
connection URL, token, and timeout are host environment settings, never intent
fields. Long jobs outlive child sessions; inspect only when state changes or a
bounded failure diagnostic is needed. Do not poll unchanged jobs every turn.
Before SSH cancellation, inspect once to bind the current remote PID.

When a configured scheduler service is used, follow
`references/cluster_mcp.md`. Preserve its manifest and idempotency bindings;
never retry an ambiguous submit or cancel with the same or a new identifier
until the scheduler state has been reconciled by the host.
An `unresolved_controls` context entry means a pre-side-effect guard has no
final result; stop automatic control and reconcile the scheduler manually.

## Evidence And Audits

- Register evidence only after verifying local source files and provenance.
- Keep TS/Freq and connectivity evidence in separate records even if one
  execution produced both.
- A candidate, scan point, NEB image, crossing point, or isolated imaginary
  frequency is not an accepted TS.
- Accepted TS requires the declared TS/Freq, connectivity, stereochemical, and
  audit gates for the same claim.
- A multistep pathway requires every elementary step and intermediate to be
  represented and audited.
- If strict R->P proof is required, failure of one branch does not complete the
  study while a scientifically meaningful branch remains.

## Backend Failure Handling

Read `references/program_runtime_failures.md` for Gaussian, optimizer, SCF,
IRC, scheduler, parser, scratch, or fetch failures. Keep technical diagnosis in
program facts. The Root Agent decides retry, recalculation, branch replacement,
hypothesis revision, user escalation, or stop.

## Render, Web, And Report

- `ts_render` writes visual artifacts only and uses `xyzrender` only.
- `ts_web` reads workspace state and attempt artifacts; it never mutates source
  workspaces or derives scientific status in browser JavaScript.
- `ts_report` runs only after workspace validation. Keep electronic, E+ZPE,
  and free energies distinct and expose missing corrections.
- Report package creation is atomic and no-overwrite. Verify
  `package_manifest.json` before using its email summary or assets.

Use `templates/ts_final_report.md` for final reporting.

## References

Load only what the current act needs:

- Node and decision semantics: `docs/RESEARCH_NODE_ONTOLOGY.md`,
  `references/state_model.md`, `references/decision_contract.md`
- Branch and history choice: `references/agent_decision_protocol.md`
- Candidate strategy: `references/candidate_generation.md`
- Gaussian and runtime failures: `references/gaussian_validation.md`,
  `references/program_runtime_failures.md`
- Connectivity: `references/connectivity_validation.md`
- Mechanism reflection: `references/mechanism_reflection.md`
- Runtime and Pi: `references/runtime_environment.md`,
  `references/pi_agent_adapter.md`
- Backend delegation: `references/compute_operator.md`,
  `references/backend_contract.md`, `references/remote_contract.md`,
  `references/cluster_mcp.md`
- Rendering and reporting: `references/render_contract.md`,
  `references/report_template.md`, `references/artifact_operators.md`
