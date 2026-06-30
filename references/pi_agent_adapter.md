# Pi Agent Adapter

This package keeps the Python workflow kernel authoritative and exposes a thin
Pi adapter around it.

## Install

Install this repository as a Pi package. For a TS task workspace, prefer
project-local installation so the package is recorded in that task directory's
`.pi/settings.json` instead of the global Pi settings:

```bash
cd /path/to/ts-workspace
pi install -l /home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor --approve
```

Install or refresh the isolated Python runtime:

```bash
python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json
```

Then start Pi from the same TS workspace:

```bash
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Pi loads:

- the root skill via `package.json` `pi.skills`;
- the context extension at `extensions/ts-workflow-context`.

`pi -e` is for loading one extension file directly; it does not load this
package manifest from the repository root. For temporary extension-only testing:

```bash
pi --skill /home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor \
  -e /home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor/extensions/ts-workflow-context/index.ts
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
python scripts/ts_workspace.py report_workspace --root <workspace>
```

It does not read or mutate workspace state files directly. `report_workspace` remains the
only report source.

If `.runtime/env.json` exists, the extension runs `scripts/ts_workspace.py` with
the manifest's `python_executable`. Without a manifest it falls back to
`python3`, matching source-checkout development behavior.

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
workspace state transitions, accepted-TS logic, Gaussian parsing, or branch-context
rules in TypeScript. Those contracts belong in Python modules and schemas.
