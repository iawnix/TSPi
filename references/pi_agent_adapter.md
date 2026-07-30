# Pi Agent Adapter

This package keeps the Python workflow kernel authoritative and exposes a thin
Pi adapter around it.

## Install

The native subagent requires Pi `0.81.1` and matching Pi SDK packages.

Pi local path installation registers a package reference; it does not copy the
skill into the TS workspace. Do not assume a local-path package root is stable
or workspace-owned.

For maintained local Codex/Pi workspaces, prefer registering the installed
Codex skill copy so both agents use the same package root:

```bash
cd /path/to/ts-workspace
pi install -l "$PWD/.agents/skills/transition-state-workflow" --approve
```

For users installing directly from GitHub, Pi stores the package checkout under
project-local `.pi/git/...` or global `~/.pi/agent/git/...`. Runtime state must
still belong to the TS workspace, not to that Git checkout:

```bash
cd /path/to/ts-workspace
pi install -l https://github.com/iawnix/TSAgentSkill --approve
```

Install or refresh the isolated Python runtime with explicit package and
workspace roots:

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

Then start Pi from the same TS workspace:

```bash
cd /path/to/ts-workspace
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Pi loads:

- the root skill via `package.json` `pi.skills`;
- the context extension at `extensions/ts-workflow-context`;
- the scientific-review extension at `extensions/ts-workflow-subagent`.

`pi -e` is for loading one extension file directly; it does not load this
package manifest from the repository root. For temporary extension-only
testing:

```bash
pi --skill "$TS_AGENT_SKILL_ROOT" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-context/index.ts" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-subagent/index.ts"
```

## Workspace Context

The extension injects a short per-turn system-prompt context only when it can
resolve a TS workspace root. For automatic prompt injection, resolution order:

1. `TS_WORKSPACE_ROOT`;
2. the nearest ancestor containing the workspace state files.

For tools and commands, an explicit `root` argument takes precedence over
environment and ancestor discovery.

The automatically injected per-turn context is derived only from:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_workspace --root <workspace>
```

It does not read or mutate workspace state files directly. Detailed historical
context is loaded only after an explicit tool call through `report_node` or
`report_branch_context`.

The extension resolves the interpreter through:

```bash
python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_runtime.py" resolve --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root <workspace> --json
```

With a workspace root, the resolver reads:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
```

It does not fall back to a development-tree `package_root/.runtime/env.json`.
Without a configured runtime it falls back to `python3`, matching
source-checkout development behavior.
`TS_AGENT_PYTHON`, when set, must be an absolute executable path.

## Tools

- `ts_workspace_context`: with no selector, run `report_workspace`; with
  `nodeId`, return a compact historical-node capsule; with both `fromNode` and
  `anchorNode`, return a backtrack comparison containing the trigger,
  checkpoint, and intervening attempts.
- `ts_workspace_validate`: run `validate_workspace`.
- `ts_workspace_decision_validate`: run workspace-aware `validate_decision`
  without mutation.
- `ts_workspace_decision`: run `start_node`, `propose_hypothesis`,
  `update_workspace`, or `end_node` using a decision JSON file.
- `ts_workspace_subagent`: run one fresh, tool-free Pi session for bounded
  advisory review in `mechanism`, `candidate`, `tsfreq`, `connectivity`,
  `final_audit`, or `program_failure` mode.

`ts_workspace_decision` is the only mutating Pi tool. It still goes through the
public `ts_workspace` CLI and inherits all validators/finalizers.

The subagent receives only a report-derived task packet, selected evidence
summaries, and up to four bounded text excerpts. It inherits no parent history,
skills, extensions, `AGENTS.md`, or tools. Use it only when an independent
review can alter the next decision, not on every turn. Its JSON output is
advisory and must be reconciled against primary artifacts and registered
evidence by the root agent before any workspace mutation or scientific
conclusion. A lightweight `ts-workspace-subagent-run` entry records run scope,
model, usage, duration, and output digest outside model context; it is not
workspace evidence.

The child recreates the selected model in a fresh `ModelRuntime`. A temporary
non-OAuth API key resolved from the parent Pi session is copied only into that
in-memory runtime; it is never included in the task packet, tool result, custom
entry, or workspace state. Providers or models that cannot be recreated fail
visibly instead of falling back to another model.

## Commands

- `/ts-context [workspace]`: show the compact workspace context widget.
- `/ts-validate [workspace]`: validate the workspace and show the result.

## Boundary

The Pi extensions must stay wrappers. Do not implement authoritative chemistry
judgments, workspace state transitions, accepted-TS logic, Gaussian parsing, or
branch-context rules in TypeScript. Those contracts belong in Python modules
and schemas.
