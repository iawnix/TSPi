# Pi Agent Adapter

The Pi package is a thin boundary around deterministic Python kernels and fresh
operator sessions. It supports Pi `>=0.81.1 <1.0.0` and is tested against the
exact SDK versions declared in `package.json`.

## Package And Runtime Paths

`pi install -l` registers a package reference. Extensions resolve the package
root from `import.meta.url`; never construct script paths from the current
working directory.

Keep runtime state workspace-owned:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
<workspace>/.agents/envs/transition-state-workflow/<environment-hash>/
```

## Loaded Surface

The package exposes one Root Skill and five extensions:

- workspace control;
- TSPi UI;
- advisory Review;
- typed compute;
- render/report/notification artifacts.

Private policy files under `src/agents/` are prompt fragments, not Pi Skills.

## Context

`before_agent_start` injects only a short reminder that a TS workspace is
active and only decision apply mutates canonical state. It does not inject the
full report every turn.

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
- `ts_workspace_decision_draft`: add identity and live report/revision binding
  to a Root-selected `ts-decision/3` action and payload.
- `ts_workspace_decision_validate`: complete dry-run preflight.
- `ts_workspace_decision_apply`: transactional canonical mutation.

The apply tool is the only Pi surface that writes scientific state.
`ts_review_disposition` writes only operational journal state.

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

`ts_subagent_compute` creates a fresh session with only the typed tool bound to
one selected operation. The runtime composes the shared compute policy with one
backend policy. It cannot select a backend, alter an intent, or update Claims.

Submit/cancel preflight occurs before child creation. Results distinguish typed
tool return, action success/failure/unknown, program status, and later report
serialization. Long jobs outlive child sessions and are inspected through new
bounded calls.

`ts_remote_inspect` is deterministic and read-only. It exposes status, doctor,
queue, and node diagnostics but no upload, submit, cancel, or arbitrary command.

## Render, Report, And Notification

Render and report each create a fresh session with one path-bound typed tool.
Host-generated results are bound to the actual action and no-overwrite artifact
paths.

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

The UI never probes infrastructure, calls a model, writes a workspace, grants
authority, or interprets chemistry.

## Result Authority

All children return `ts-agent-result/1`. The host rejects fields that attempt
to set Claim status, Claim updates, Gate verdicts, audit decisions, accepted
refs, or study completion. Operator output becomes useful scientific Evidence
only after local verification and a normal workspace decision.
