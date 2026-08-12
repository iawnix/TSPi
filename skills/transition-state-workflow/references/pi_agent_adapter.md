# Pi Agent Adapter

The Pi package is a thin adapter around the Python workspace and compute
kernels. It supports Pi `>=0.81.1 <1.0.0` and is currently tested with Pi
`0.83.0`.

## Package And Runtime Paths

`pi install -l` registers a package reference. It does not copy the skill into
the current workspace. Direct GitHub installation uses a Pi-managed checkout
under project-local `.pi/git/...` or global Pi state.

Never construct script paths from the current working directory. Extensions
resolve the package root from `import.meta.url`.

Keep the Python runtime workspace-owned:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/resolved/TSAgentSkill
export TS_WORKSPACE_ROOT=/path/to/ts-workspace
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --workspace-root "$TS_WORKSPACE_ROOT" \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

Default manifest and environment store:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
<workspace>/.agents/envs/transition-state-workflow/<environment-hash>/
```

Separate Pi research workspaces therefore use separate full prefixes unless
they deliberately share `TS_AGENT_ENV_ROOT`.

## Load

Package installation loads the root skill and five extensions declared in
`package.json`:

- `extensions/ts-workflow-control`
- `extensions/ts-workflow-ui`
- `extensions/ts-workflow-review`
- `extensions/ts-workflow-compute`
- `extensions/ts-workflow-artifacts`

Temporary extension-only smoke:

```bash
pi --skill "$TS_AGENT_SKILL_ROOT/skills/transition-state-workflow" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-control/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-ui/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-review/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-compute/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-artifacts/index.ts"
```

## Context Policy

`before_agent_start` injects only this kind of reminder:

```text
TS workspace active: <root>. Use ts_workspace_context on demand; only ts_workspace_decision_apply mutates canonical state.
```

It does not execute `report_workspace` every turn. Context is pulled through
`ts_workspace_context`:

- `summary`: current compact read model
- `delta`: distinguish scientific and operational changes using
  `sinceRevision` and `sinceOperationalRevision`
- `node`: one historical node capsule
- `branch`: trigger, selected checkpoint, and intervening attempts
- `audit`: audit-oriented current read model

Workspace resolution order is explicit `root`, `TS_WORKSPACE_ROOT`, then nearest
ancestor containing canonical state files.

## Four Workspace Tools

- `ts_workspace_context`: read-only context.
- `ts_workspace_decision_draft`: Root Agent-selected action plus payload becomes a
  non-mutating `ts-decision/2` with current report and revision.
- `ts_workspace_decision_validate`: workspace-aware preflight of the supplied decision
  object through a private temporary file.
- `ts_workspace_decision_apply`: invoke the matching mutation command transactionally,
  then return refreshed compact context.

`ts_workspace_decision_apply` is the only mutating Pi workspace tool. The action is read
from the validated decision; there is no model-supplied shell command.

## Review Subagent

`ts_subagent_review` creates a fresh in-memory, tool-free Pi session for one
bounded review. It receives:

- one `ts-agent-task/1` packet;
- compact report/node/branch context selected by the Root Agent;
- allowlisted evidence summaries;
- at most four bounded text excerpts;
- one review-mode prompt.

It receives no parent conversation, context files, root skills, extensions,
workspace tools, decision files, or preflight output. Its `ts-agent-result/1`
is advisory and must cite the packet allowlist.

Run metadata remains available through Pi `appendEntry`, and the host also
persists an immutable workspace journal under `nodes/<node>/agent-runs/` or
`operations/agent-runs/`. The journal records task, actions, result, status,
model metadata, duration, and bounded failures. It is noncanonical operational
state, never scientific evidence.

The child recreates the selected model. A temporary
non-OAuth API key may be copied into the child runtime in memory; it is never
included in packets, results, entries, or workspace files. Model fallback is
rejected.

## Compute Subagent

`ts_remote_inspect` gives the Root Agent an on-demand read-only SSH/Torque
surface with `status`, `doctor`, `queues`, and `nodes` modes. Use `doctor` for
the complete environment check and `queues` or `nodes` for focused scheduler
views. The equivalent user command is `/ts-remote status|doctor|queues|nodes`. Neither surface
uploads files, controls jobs, or injects a remote report every turn.

`ts_subagent_compute` creates a separate fresh session with only the
typed tools needed for one operation. The Root Agent supplies the selected
backend. The runtime composes `src/agents/compute/policy.md` with exactly one
matching file under `src/agents/compute/backends/`; no other backend policy
enters the child context. These files are prompt policies, not Pi skills.

Available operations are `prepare`, `submit`, `inspect`, `collect`, `cancel`,
and `parse`. The Root Agent can run submit and cancel directly in interactive or
headless Pi after exact intent binding. The deterministic compute preflight
validates the configured profile, workspace path, resources, and control
binding before child creation. The output validator binds IDs, state, program
outcome, error class, and artifact refs to actual typed-tool results.

Model output is passed directly to the versioned JSON contract. Top-level
`outcome=completed`, singular fact `artifact_ref`, non-canonical fact kinds,
unknown outcomes, unbound basis refs, and authoritative scientific fields are
rejected rather than converted.

Long-running jobs are external processes, not persistent LLM sessions. Invoke
`inspect` on meaningful state changes or failure diagnosis, not every turn.

## Artifact Subagents

- `ts_subagent_render`: one node-owned local render with allowlisted
  inputs and one new output path.
- `ts_subagent_report`: one validated report package under
  `reports/`.

Each creates a fresh session with exactly one private artifact policy and one
typed tool. Request paths reject traversal, symlinks, and overwrite. Output
validators bind artifacts and role payloads to the actual typed action.

Report packages are published atomically with a `ts-report-package/1`
`package_manifest.json`. The manifest binds the source scientific revision and
all package files by SHA-256.

`ts_notify_user` is a separate deterministic Root Agent tool. It accepts a
research event, subject, summary, and optional `reports/` refs, while recipient
and ClawEmail configuration remain installation-owned. It creates no child
session and uses digest-addressed delivery receipts as described in
`references/artifact_operators.md`.

## Communication Protocol

All review, backend, render, and report delegation uses:

- `ts-agent-task/1`
- `ts-agent-result/1`
- `ts-subagent-status/1` for transient UI-only lifecycle updates

The result validator recursively rejects fields owned by the Root Agent,
including hypothesis status, branch context, claim verdict, accepted TS,
strict pathway decision, and study completion.

The UI lifecycle progresses through `preflight`, `starting`, `running`, and
`validating`, followed by `completed`, `failed`, or `cancelled`. `running` is
emitted only after the isolated child session exists. The UI extension renders
these updates through Pi status/widget APIs and existing run journal entries;
it registers no tools and never changes compute approval or scientific state.

## Boundary

Keep TypeScript wrappers thin. State transitions, evidence gates, topology,
backend preparation, deterministic parsing, and scientific acceptance remain
in Python modules and versioned schemas.
