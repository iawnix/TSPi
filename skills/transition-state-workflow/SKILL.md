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
- Cluster submission or cancellation runs only through the pre-bound compute
  operator; never expose raw transport controls or retry ambiguous results.
- `ts_web` is read-only.
- Email delivery requires an explicitly activated fixed-scope policy; without
  one, only a local draft may be created.

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

Read `references/research_node_ontology.md` and `references/state_model.md` when node
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
2. `ts_workspace_decision_draft`: non-mutating `ts-decision/2` draft.
3. `ts_workspace_decision_validate`: workspace-aware preflight.
4. `ts_workspace_decision_apply`: transactional mutation and refreshed compact context.

Only `ts_workspace_decision_apply` mutates canonical state. Do not hand-edit decision or
state files between decide, validate, and apply. A stale `base_revision` is
rejected.

Pi injects only a short control-plane reminder at turn start, not the full
workspace report. Use `mode=delta` with the last scientific and operational
revisions. Load historical context only when needed:

- `mode=node, nodeId=<id>` for one checkpoint;
- `mode=branch, fromNode=<trigger>, anchorNode=<checkpoint>` before backtrack;
- `mode=audit` before acceptance or completion review.

Construct decisions from `references/decision_contract.md`. Files under
`assets/templates/decision/` are minimal v2 examples; tests are fixtures, not
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

Every `ts_subagent_*` tool creates a fresh child model session. In contrast,
`ts_workspace_*` tools call the deterministic workspace control plane directly,
and `ts_remote_*` tools run deterministic infrastructure diagnostics.

Use `ts_subagent_review` only at high-value ambiguity, failure-analysis,
backtrack, or audit boundaries. Each call creates a fresh tool-free session
with no parent history, root skills, extensions, `AGENTS.md`, or workspace
write access.

Use `ts_subagent_compute` for one bound `prepare`, `submit`,
`inspect`, `collect`, `cancel`, or `parse` operation. Pass the backend selected
by the Root Agent. The child gets only request-scoped typed tools, the shared
compute policy, and one selected backend policy. It cannot select methods,
change the intent, register evidence, or set a scientific status. For `submit`
and `cancel`, the Root Agent directly creates a child with one operation bound
to the current intent digest and target; no separate interactive approval is
required.

Use `ts_remote_inspect` for cluster status, resource availability, remote
preparation, queue selection, or connection diagnosis. Use `mode=cluster` for
an aggregate view and `status`, `doctor`, `queues`, or `nodes` for narrower
checks. The profile comes from the active calculation intent or the configured
default. Do not call the diagnostic every turn or poll an unchanged
connection. Users may run the same checks with
`/ts-remote status|doctor|queues|nodes|cluster`. Submit, cancel, upload, and
arbitrary remote commands are not exposed by this diagnostic surface.

Use `ts_subagent_render` for one node-owned local render,
`ts_subagent_report` for one new validated report package, and
`ts_subagent_email_draft` for one local email draft from a generated report
summary. Each child gets the shared artifact policy, one selected role policy,
and one path-bound typed tool. The email subagent cannot send, access a network,
select a sender, infer addresses, or read credentials.

After a fixed-template draft exists, use `ts_email_send` only when the user has
previously activated the workspace-private delivery policy. The deterministic
host verifies the exact recipients, `ts-report-summary/1` template, report
manifest digests, configured attachment names, ClawEmail installation, and
delivery receipt. It does not ask for per-call approval when the active policy
matches. A missing, changed, or mismatched policy leaves the draft local.

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

For `ts_subagent_compute operation=prepare`, declare the scientific purpose,
backend task, attempt kind, input roles, settings, execution target, and whether
the request is dry-run only. The deterministic host derives `validation_scope`
from the selected node and creates the `ts-calculation-intent/2` ID, attempt
directory, canonical input refs, expected artifact paths, authority, and remote
directory. Do not hand-write an intent file or choose generated filenames.

First call `ts_workspace_context mode=artifacts` and select the required
`artifactId` plus `inputRole` bindings. Pass every required role through
`inputArtifacts`; do not pass paths or filenames to compute preparation. The
kernel resolves each logical ID and freezes its path and SHA-256 in the intent.
The Root Agent still selects methods, settings, resources, retry vs
recalculation, node and branch order, and all scientific interpretation. The
generated layout is an operational storage contract, not a fixed research phase
engine.

Attempt authority lives under:

```text
nodes/<node>/attempts/<intent>/
```

A remote request selects one installation-owned profile and complete scheduler
resources. The host generates `authority=execution_mirror`, workspace identity,
and the remote directory. SSH hosts, remote roots, scheduler commands, software
activation, and environment are profile settings, never intent fields. Long
jobs outlive child sessions; inspect only when state changes or a bounded
failure diagnostic is needed. Do not poll unchanged jobs every turn.

Follow `references/remote_contract.md`. Preserve its manifest and idempotency bindings;
never retry an ambiguous submit or cancel with the same or a new identifier
until the scheduler state has been reconciled by the host.
Use `pending_controls` for a guard with no final result. Use
`unresolved_controls` for a completed control attempt that still needs a safe
retry or reconciliation. Retry the same submission ID only when the typed
control outcome says `retry_disposition=retry_same_submission` and
`effect_attempted=false`; never replay an ambiguous scheduler request.
Gaussian submission requires a configured `software.gaussian` profile with an
existing activation script and an allowed queue. Installation of `g16` alone is
not registration. Do not bypass a failed profile preflight with a PATH override.

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

Use `assets/templates/ts_final_report.md` for final reporting.

## References

Load only what the current act needs:

- Node and decision semantics: `references/research_node_ontology.md`,
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
  `references/backend_contract.md`, `references/remote_contract.md`
- Rendering and reporting: `references/render_contract.md`,
  `references/report_template.md`, `references/artifact_operators.md`
