# TSAgentSkill Architecture

This document is the authority for component ownership and runtime boundaries in
`@iawnix/ts-agent` v3. JSON schemas remain authoritative for field-level call
shapes, and the Root Skill remains authoritative for research-session behavior.

## System Shape

```text
Installation root
  TSPi shell shim
    -> Python lifecycle host
       -> active immutable release
       -> shared isolated Python runtime
       -> selected workspace bootstrap and Root lock
       -> Pi process
          -> Root Skill
          -> five Pi extensions
          -> Root Agent session
             -> Workspace Kernel
             -> advisory Review Agent
             -> bounded compute/render/report operator sessions
             -> deterministic remote and notification services
          -> read-only TSPi UI projection
```

There are three different forms of execution and they must not be conflated:

1. **Root Agent reasoning** selects scientific questions, Claims, methods,
   branch topology, retries, stopping, and interpretation.
2. **Advisory Agent reasoning** is currently used only by Review. It analyzes a
   bounded Claim dependency snapshot and returns non-authoritative advice.
3. **Deterministic or bounded operation** validates data, mutates state through
   one owner, or executes a preselected action. Compute, Render, and Report use
   fresh model sessions as constrained dispatchers today, but their scientific
   inputs and action effects are host-bound and their results are generated or
   validated by deterministic code.

The presence of a child model session does not grant scientific authority.

## Authority Matrix

| Component | Uses a model | Writes canonical science | External effect | Durable output |
| --- | --- | --- | --- | --- |
| TSPi lifecycle host | No | Bootstrap only | Starts Pi | release/config selection, workspace identity, lock file |
| Root Agent | Yes | Only through Kernel apply | Selects bounded tools | Pi session plus Decisions it applies |
| Workspace Kernel | No | Yes, exclusively | No | canonical registries, Nodes, Decisions, transactions |
| Review Agent | Yes | No | No | task, bound inputs, result/failure, Root disposition |
| Compute operator session | Yes, constrained | No | Bound local/remote action | run journal plus calculation control records |
| Render/Report operator session | Yes, constrained | No | Bound local file creation | run journal plus no-overwrite artifact/package |
| `ts_remote` | No | No | SSH/SCP and Torque | guards, receipts, status, collected artifacts |
| `ts_notify_user` | No | No | Fixed-target ClawEmail delivery | digest-addressed delivery receipt |
| TSPi UI | No | No | No | transient activity only |
| `ts_web` | No | No | No scientific effect | explicit read-only UI registry outside source state |

Only `ts_workspace_decision_apply` may mutate canonical scientific state after
bootstrap. No Review, operator, scheduler, parser, renderer, report builder,
notification, or UI event can bypass that boundary.

## Scientific State Model

The v3 model contains four long-lived concepts:

- **Node** records one bounded act, its parent, objective, descriptive tags,
  refs, and terminal result.
- **Claim** records a versioned Root-authored scientific statement, required
  Gates, cited support, status, and history.
- **Evidence** records immutable facts, artifacts, source tier, and provenance.
  It has no workflow role or layer. Corrections use superseding records or
  lifecycle events.
- **Gate** records the deterministic evaluation of active Evidence facts under
  one named policy for one target.

Closed schema enums exist only where code must execute a closed contract. The
Kernel therefore has Decision actions, Node states/outcomes, Evidence lifecycle
states, and Gate names, but it has no research phase, workflow stage, Node type,
Evidence role, or strategy router. Node tags never authorize an action.

The normal mutation sequence is:

```text
context -> decision draft -> complete dry-run validation -> apply under lock
```

Draft allocates technical Decision, Evidence, and Gate-result IDs and binds the
current report and scientific revision. Validate is non-mutating. Apply repeats
validation while holding the workspace lock and commits through the same
transaction path. A validated Decision is not a reusable token, and callers
must not edit it before apply.

## Scientific, Operational, And Presentation State

### Canonical scientific state

```text
research_state.json
claims.json
evidence_registry.json
gate_results.json
nodes/<node_id>/node.json
accepted/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

These files determine `workspace_revision`.

### Operational state

Calculation attempts, immutable intents, scheduler controls, remote receipts,
Review/operator runs, Root Review dispositions, reports, and notification
receipts determine `operational_revision` or remain derived artifacts. They do
not silently change Claims, Evidence, Gates, or accepted artifacts.

### Presentation state

`TS Activity`, working text, expanded entries, and the in-memory activity store
are presentation only. They are cleared on Pi session start and shutdown. The
activity panel is not rebuilt automatically from journals. The
`/ts-subagent-history` browser explicitly reads durable run summaries and merges
them with any current in-memory activity.

## TSPi Lifecycle

`TSPi` is a thin shell shim. `scripts/tspi_host.py` and
`ts_runtime/launcher.py` own lifecycle behavior:

1. Resolve the installation root and verify that the invoking package is the
   immutable release selected by `.pi/packages/ts-agent/current`.
2. Select installation-owned runtime, remote, notification, and cache paths.
3. Resolve the shared isolated Python runtime before importing workflow code.
4. For normal startup, validate the workspace name and create or reuse
   `<installation>/workspaces/<name>`.
5. Create workspace-local Pi session settings and acquire a nonblocking Root
   Agent `flock`.
6. Initialize a fresh workspace once, validate a complete v3 workspace without
   rewriting it, or fail closed for partial, invalid, or v2 state.
7. `exec` Pi with exactly the package Skill, theme, and five extensions.

One workspace has one Root Agent writer process. Different workspace names may
run concurrently and share the immutable release and Python environment without
sharing sessions, canonical state, calculation controls, or reports.

A Pi session contains multiple user/assistant turns. Starting a terminal TSPi
process does not resume a prior Pi conversation unless Pi's `--continue` is
passed. Phone mode uses `--continue` automatically. Node completion changes the
workspace, not the model transcript: the next Agent turn sees those changes
only through the tool result already in context or a later
`ts_workspace_context` read.

Before each Root Agent run, the control extension appends a short package-source
policy and active-workspace reminder to Pi's existing system prompt. It does not
inject the full workspace report on every turn.

## Public Extensions

| Extension | Public tools and commands | Responsibility |
| --- | --- | --- |
| `ts-workflow-control` | `ts_workspace_context`, draft, validate, apply; `/ts-context`, `/ts-validate` | Context projection and the only scientific mutation path |
| `ts-workflow-review` | `ts_subagent_review`, `ts_review_disposition` | Bounded advisory Review and mandatory Root response journal |
| `ts-workflow-compute` | `ts_subagent_compute`, `ts_remote_inspect`; `/ts-remote` | Typed calculation operations and read-only infrastructure diagnostics |
| `ts-workflow-artifacts` | `ts_subagent_render`, `ts_subagent_report`, `ts_notify_user` | Local artifacts, report packages, and fixed-target delivery |
| `ts-workflow-ui` | `/ts-subagent-history` | Header, editor, footer, activity, history, and presentation only |

`ts-phone-bridge` is optional and loaded only by `TSPi --phone`; it is not one
of the normal five extensions. It feeds messages into the same visible Pi
process and does not create a hidden Root Agent.

The shared `tool-catalog.ts` records public names and coarse execution kinds.
It is an inventory, not a full capability contract. Field shapes live in each
registered TypeBox schema, static compute support lives in
`ts_compute/capabilities.py`, and live readiness requires explicit diagnostics.

## Root Context And Package Sources

The Root Agent learns ordinary operation from these sources, in order:

1. Registered tool schemas and prompt guidelines for accepted call fields.
2. `ts_workspace_context mode=artifacts|capabilities` for live logical inputs
   and static adapter support.
3. The public Root Skill, focused references, and reusable assets.

Implementation source and tests are maintenance material, not runtime examples.
The package-source guard blocks structured reads into private package paths
during research sessions. It is a routing guard rather than a general
filesystem sandbox.

## Review Agent Runtime

Review is the only child whose intended result depends on independent scientific
reasoning. The host:

1. Selects one target Claim and asks the Kernel for its deterministic dependency
   snapshot.
2. Binds a full `ts-review-evidence-snapshot/2` for host citation validation.
3. Projects a compact `ts-review-provider-input/2` for the model.
4. Starts a fresh Pi session with no parent history, Skills, extensions,
   built-in tools, raw filesystem access, or recursive delegation.
5. Enables exactly one `ts_review_result` tool and forces that named tool call.
6. Validates the result locally against `ts-agent-result/1`, task identity, and
   the full citation allowlist.
7. Allows at most one format repair in the same session.

The provider projection is limited to 24 KiB, with at most 8 Claims, 32 Gate
results, 32 Evidence records, 16 Nodes, 4 artifact excerpts, and 8 KiB of model
visible excerpt text. The full local snapshot may be larger, up to 96 KiB.
Provider HTTP or stream failure outranks missing-tool or schema failure.

A successful Review remains advisory until the Root Agent records exactly one
`ts_review_disposition`. Even accepted advice requires normal Decisions and
primary Evidence before it changes science.

## Bounded Operator Sessions

Compute, Render, and Report also start fresh Pi child sessions, but their role is
different from Review:

- the Root Agent and host bind the operation, inputs, capabilities, paths, and
  expected effect before session creation;
- the child receives only request-scoped typed tools;
- Compute may provide a short operational summary, while the host derives
  authoritative action fields from typed results;
- Render and Report results are generated from the actual typed action and
  verified output, not restated by the model;
- no operator can select a method, update a Claim, evaluate a Gate, or accept a
  TS.

These sessions use `ts-agent-task/2` and `ts-agent-result/1` because isolation,
timeout, provenance, and UI lifecycle are shared. That common envelope does not
make them scientific reviewers.

## Run Journals And Result Delivery

Review/operator journals live under one owning Node when the task has exactly
one Node, otherwise under study-level operations:

```text
nodes/<node_id>/agent-runs/<task_id>/
operations/agent-runs/<task_id>/
```

At creation, `task.json` and any bound Review documents are written atomically.
On normal terminal handling, the host writes `actions.json`, optional
`result.json`, and `run.json` with `completed` or `failed`. Files are private,
exclusive-create journal records.

Current durability has explicit limits:

- a process crash after task creation but before terminal handling leaves no
  `run.json`; the operational reader reports that run as pending/unknown;
- action arrays are accumulated in memory and written at terminal handling,
  rather than appended after each tool effect;
- Review explicitly observes provider HTTP/stream failures; other operator
  sessions rely on errors propagated by the Pi runtime and may retain less
  provider-specific detail;
- the public tool return is the immediate result-delivery channel. There is no
  separate durable delivery acknowledgement or automatic replay into a later
  Root turn.

Remote compute effects are protected separately by calculation guards,
submission records, and receipts. If a child response is lost after a remote
effect, reconcile those control records and local artifacts; do not infer safety
from a missing child `result.json` and do not replay an ambiguous scheduler
request.

## Compute And Remote Lifecycle

The Root Agent chooses scientific purpose, backend, task, settings, execution
kind, profile, and bounded resources. The deterministic adapter resolves
logical artifacts and creates the intent, paths, generated inputs, expected
artifacts, digests, and submission identity.

```text
Root-selected typed request
  -> ts_compute intent and local attempt
  -> ts_backends preparation/parsing
  -> optional ts_remote OpenSSH/SCP and Torque
```

`ts_remote` is the only remote subsystem. Installation configuration owns SSH
host aliases, scheduler commands, roots, queues, software commands, activation,
scratch policy, and environment. The request cannot override them.

Submit separates pre-effect staging failure, known scheduler rejection, known
job ID, and ambiguous request effect. Status keeps scheduler state and program
state separate. Collection verifies only declared files and hashes and never
depends on `qstat` history. Scheduler status is operational, not Evidence.

## Failure And Recovery Rules

- Scientific state corruption or a partial v3 workspace fails closed at
  startup; it is not repaired opportunistically.
- A failed program normally leaves the Claim unresolved. Scientifically useful
  negative results require completed, verified artifacts and normal Evidence.
- A pre-effect remote staging failure may be retried only with the exact binding
  and an explicit retry disposition.
- Ambiguous submit, cancel, or notification effects are never retried
  automatically.
- A Review provider failure is a failed operational run, not a scientific
  opinion and not a format-repair result.
- Render or report action success is checked against the actual output and
  manifest even if the outer child response fails.
- Reports and web views are projections; they cannot repair or override source
  state.

## Contract Locations

| Contract | Source of truth |
| --- | --- |
| Scientific records and Decisions | `ts_workspace/contracts/` plus Kernel validators |
| Gate policies | `ts_workspace/contracts/gate_policies.json` plus `gates_v3.py` |
| Compute request, intent, and result | `ts_compute/contracts/` plus adapters |
| Agent task and result | `contracts/` plus `src/agent-core/agent-protocol.cjs` |
| Review packet and citation limits | `src/agents/review/task-packet.cjs` |
| Public tool names | `extensions/shared/tool-catalog.ts` |
| Installed release boundary | `package.json.files`, `scripts/check_package.py`, installer checks |
| Root operating policy | `skills/transition-state-workflow/SKILL.md` and focused references |

When code, schema, tool help, Skill text, examples, and tests disagree, the
package is not documentation-complete. Repair the owning contract and all of its
projections together.
