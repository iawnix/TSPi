# Pi Agent Adapter

This package keeps the Python workflow kernel authoritative and exposes a thin
Pi adapter around it.

## Install

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
- the context extension at `extensions/ts-workflow-context`.

`pi -e` is for loading one extension file directly; it does not load this
package manifest from the repository root. For temporary extension-only
testing:

```bash
pi --skill "$TS_AGENT_SKILL_ROOT" \
  -e "$TS_AGENT_SKILL_ROOT/extensions/ts-workflow-context/index.ts"
```

## Workspace Context

The extension injects a short per-turn system-prompt context only when it can
resolve a TS workspace root. For automatic prompt injection, resolution order:

1. `TS_WORKSPACE_ROOT`;
2. the nearest ancestor containing the workspace state files.

For tools and commands, an explicit `root` argument takes precedence over
environment and ancestor discovery.

The injected context is derived only from:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_workspace --root <workspace>
```

It does not read or mutate workspace state files directly. `report_workspace`
remains the only report source.

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

## Tools

- `ts_workspace_context`: run `report_workspace` and return a compact summary.
- `ts_workspace_validate`: run `validate_workspace`.
- `ts_workspace_decision`: run `validate_decision`, `start_node`,
  `update_workspace`, or `end_node` using a decision JSON file.

`ts_workspace_decision` is the only mutating Pi tool. It still goes through the
public `ts_workspace` CLI and inherits all validators/finalizers.

## Commands

- `/ts-context [workspace]`: show the compact workspace context widget.
- `/ts-validate [workspace]`: validate the workspace and show the result.

## Boundary

The Pi extension must stay a wrapper. Do not implement chemistry judgments,
workspace state transitions, accepted-TS logic, Gaussian parsing, or
branch-context rules in TypeScript. Those contracts belong in Python modules
and schemas.
