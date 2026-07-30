# Pi Agent Adapter

The Pi package is a thin adapter around the Python workspace and compute
kernels. It supports Pi `0.81.1`.

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

Separate Pi and Codex workspaces therefore use separate full prefixes unless
they deliberately share `TS_AGENT_ENV_ROOT`.

## Load

Package installation loads the root skill and three extensions declared in
`package.json`:

- `extensions/ts-workflow-context`
- `extensions/ts-workflow-subagent`
- `extensions/ts-workflow-compute`

Temporary extension-only smoke:

```bash
pi --skill "$TS_AGENT_SKILL_ROOT" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-context/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-subagent/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-compute/index.ts"
```

## Context Policy

`before_agent_start` injects only this kind of reminder:

```text
TS workspace active: <root>. Use ts_workspace_context on demand; only ts_workspace_apply mutates canonical state.
```

It does not execute `report_workspace` every turn. Context is pulled through
`ts_workspace_context`:

- `summary`: current compact read model
- `delta`: return no repeated summary when `sinceRevision` is unchanged
- `node`: one historical node capsule
- `branch`: trigger, selected checkpoint, and intervening attempts
- `audit`: audit-oriented current read model

Workspace resolution order is explicit `root`, `TS_WORKSPACE_ROOT`, then nearest
ancestor containing canonical state files.

## Four Workspace Tools

- `ts_workspace_context`: read-only context.
- `ts_workspace_decide`: Root Agent-selected action plus payload becomes a
  non-mutating `ts-decision/2` with current report and revision.
- `ts_workspace_validate`: workspace-aware preflight of the supplied decision
  object through a private temporary file.
- `ts_workspace_apply`: invoke the matching mutation command transactionally,
  then return refreshed compact context.

`ts_workspace_apply` is the only mutating Pi workspace tool. The action is read
from the validated decision; there is no model-supplied shell command.

## Review Subagent

`ts_workspace_subagent` creates a fresh in-memory, tool-free Pi session for one
bounded review. It receives:

- one `ts-agent-task/1` packet;
- compact report/node/branch context selected by the Root Agent;
- allowlisted evidence summaries;
- at most four bounded text excerpts;
- one review-mode prompt.

It receives no parent conversation, context files, root skills, extensions,
workspace tools, decision files, or preflight output. Its `ts-agent-result/1`
is advisory and must cite the packet allowlist.

Run metadata is recorded with `appendEntry` outside canonical workspace state.
It records scope, model, usage, duration, and output digest, not scientific
evidence.

The child recreates the selected model. A temporary
non-OAuth API key may be copied into the child runtime in memory; it is never
included in packets, results, entries, or workspace files. Model fallback is
rejected.

## Backend Operator

`ts_workspace_compute_operator` creates a separate fresh session with only the
typed tools needed for one operation. The Root Agent supplies the selected
backend. The runtime loads exactly one matching private backend skill from
`agent-skills/`; no other private skill enters the child context.

Available operations are `prepare`, `inspect`, `collect`, and `parse`. Submit
and cancel are absent. The output validator binds IDs, state, program outcome,
error class, and artifact refs to actual typed-tool results.

Long-running jobs are external processes, not persistent LLM sessions. Invoke
`inspect` on meaningful state changes or failure diagnosis, not every turn.

## Communication Protocol

Both review and backend delegation use:

- `ts-agent-task/1`
- `ts-agent-result/1`

The result validator recursively rejects fields owned by the Root Agent,
including hypothesis status, branch context, claim verdict, accepted TS,
strict pathway decision, and study completion.

## Boundary

Keep TypeScript wrappers thin. State transitions, evidence gates, topology,
backend preparation, deterministic parsing, and scientific acceptance remain
in Python modules and versioned schemas.
