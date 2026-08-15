# Pi Agent Adapter

The Pi package is a boundary around deterministic Python kernels, one advisory
Review Agent, and fresh bounded operator sessions. It supports Pi
`>=0.81.1 <1.0.0` and is tested against the exact SDK versions declared in
`package.json`.

## Contents

- [Package And Runtime Paths](#package-and-runtime-paths)
- [Loaded Surface](#loaded-surface)
- [Context](#context)
- [Workspace Tools](#workspace-tools)
- [Review](#review)
- [Compute](#compute)
- [Render, Report, And Notification](#render-report-and-notification)
- [UI Lifecycle](#ui-lifecycle)
- [Result Authority](#result-authority)

## Package And Runtime Paths

Normal TSPi startup loads the active versioned release from
`<installation>/.pi/packages/ts-agent/current`. Extensions resolve that package
root from `import.meta.url`; never construct script paths from the current
working directory. Package development occurs in the separate authored
checkout, then reaches TSPi through a validated release installation.

The shell launcher delegates to the package Python host. The host validates
that its package is the active `current` release, resolves installation-owned
configuration and runtime paths, selects and bootstraps one workspace, holds
its Root Agent lock across Pi `exec`, and then loads the bounded Pi surface.
Ordinary startup performs no remote probe.

Installed TSPi processes share one installation-owned runtime selected by the
Python lifecycle host:

```text
<installation>/.agents/runtime/transition-state-workflow/env.json
<installation>/.agents/envs/transition-state-workflow/<environment-hash>/
```

`TS_WORKSPACE_ROOT` still identifies the selected research workspace; sharing
the interpreter does not share sessions or research state. Direct package
scripts that receive a workspace root and no installation overrides default to
workspace-owned runtime paths. See `runtime_environment.md` for the complete
resolver contract.

## Loaded Surface

The package exposes one Root Skill and five normal extensions:

- workspace control;
- TSPi UI;
- advisory Review;
- typed compute;
- render/report/notification artifacts.

Private policy files under `src/agents/` are prompt fragments, not Pi Skills.
The optional Phone bridge is loaded only by `TSPi --phone` and feeds the same
visible Root process; it is not a sixth normal extension or another Agent.

## Context

`before_agent_start` injects only a short reminder that a TS workspace is
active and only decision apply mutates canonical state. It does not inject the
full report every turn.

A Pi session may contain many Root turns. Applying or closing a Node updates the
workspace but does not push a fresh report into later model context
automatically. Use the current tool result or call `ts_workspace_context` again.

`ts_workspace_context` modes are:

- `summary`: compact current read model;
- `delta`: scientific and operational changes since known revisions;
- `node`: one historical Node capsule;
- `lineage`: one ancestor and the Node delta after it;
- `audit`: acceptance-oriented projection;
- `artifacts`: logical compute input catalog;
- `capabilities`: static adapter support.

The lineage view is descriptive only. The Root Agent decides whether to reuse
anything or open a child Node.

## Workspace Tools

- `ts_workspace_context`: read-only.
- `ts_workspace_decision_draft`: add Decision/Evidence/Gate-result identity and
  live report/revision binding to a Root-selected action and payload.
- `ts_workspace_decision_validate`: complete dry-run preflight.
- `ts_workspace_decision_apply`: transactional canonical mutation.

The apply tool is the only Pi surface that writes scientific state.
`ts_review_disposition` writes only operational journal state.
Draft callers omit Evidence `evidence_id` and Gate `gate_result_id`; the Kernel
returns them in the canonical Decision and `allocated_refs`.

## Review

`ts_subagent_review` builds one deterministic dependency snapshot for the
selected target Claim, then creates a fresh child session with exactly one
`ts_review_result` tool. The child receives no parent conversation, Root Skill,
extensions, workspace write tools, or raw filesystem access.

The host persists and digest-binds:

- `task.json` using `ts-agent-task/2`;
- `evidence-snapshot.json` using `ts-review-evidence-snapshot/2`;
- `provider-input.json` using `ts-review-provider-input/2`;
- actions, result or failure, and run metadata.

The model sees the compact provider input. The host validates its citations
against the full snapshot. `basis_allowlist` is a set of citable refs; the host
serializes it in stable lexicographic order and validates membership without
depending on registry order. One invalid result may be repaired once in the
same session. A provider HTTP/stream failure stops immediately and must not be
reported as missing tool output.

After success, the Root Agent records one write-once disposition. It remains
advisory and non-scientific.

## Compute

`ts_subagent_compute` creates a fresh constrained operator session with only the
typed tool bound to one selected operation. The runtime composes the shared
compute policy with one backend policy. It cannot select a backend, alter an
intent, or update Claims. Its child model may summarize the operation, but the
host derives authoritative action fields from the typed result.

Submit/cancel preflight occurs before child creation. Results distinguish typed
tool return, action success/failure/unknown, program status, and later report
serialization. Long jobs outlive child sessions and are inspected through new
bounded calls.

`ts_remote_inspect` is deterministic and read-only. It exposes status, doctor,
queue, and node diagnostics but no upload, submit, cancel, or arbitrary command.

## Render, Report, And Notification

Render and Report each create a fresh constrained operator session with one
path-bound typed tool. Host-generated results are bound to the actual action,
verified output, and no-overwrite artifact paths. They do not perform
independent scientific Review.

`ts_notify_user` is deterministic. The installation owns recipient and
credentials; the Root Agent supplies a bounded research event and existing
report attachments. TSPi exposes the fixed target to the UI and tool metadata
for a pre-send mismatch check, but neither the Agent nor message text can
override it. Delivery journals are operational and idempotent.

## UI Lifecycle

`ts-subagent-status/2` updates are transient presentation events. The shared UI
observes queued, starting, running, waiting, validating, and terminal states.
Other extensions publish structured activity but do not own footer or widget
state.

The activity store is cleared on session start and shutdown and is not rebuilt
automatically. `/ts-subagent-history` reads durable run summaries on demand and
merges them with live activity. Pi's native `Ctrl+O` still expands or collapses
all expandable transcript entries; it is separate from the paginated history
browser.

The UI never probes infrastructure, calls a model, writes a workspace, grants
authority, or interprets chemistry.

## Result Authority

All child sessions return `ts-agent-result/1`. The host rejects fields that
attempt to set Claim status, Claim updates, Gate verdicts, audit decisions,
accepted refs, or study completion. Operator output becomes useful scientific
Evidence only after local verification and a normal workspace Decision.

At child creation, the journal atomically stores `task.json` and any bound
Review documents. `actions.json`, optional `result.json`, and terminal
`run.json` are written during normal completion/failure handling. A host crash
before that point leaves a task-only run reported as pending/unknown. Public
tool return is the immediate result channel; no durable acknowledgement replays
an earlier result into a later Root turn. For remote recovery, inspect the
independent calculation guards and receipts before retrying any effect.
