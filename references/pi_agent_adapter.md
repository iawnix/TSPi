# Pi Agent Adapter

This package keeps the Python workflow kernel authoritative and exposes a thin
Pi adapter around it.

## Install Or Run

From this package directory:

```bash
pi -e .
```

Or install from a git/local package source:

```bash
pi install /path/to/transition-state-workflow-refactor
```

Pi loads:

- the root skill via `package.json` `pi.skills`;
- the context extension at `extensions/ts-workflow-context`.

## Workspace Context

The extension injects a short per-turn system-prompt context only when it can
resolve a TS workspace root. For automatic prompt injection, resolution order:

1. `TS_WORKSPACE_ROOT`;
2. the nearest ancestor containing the workspace ledgers.

For tools and commands, an explicit `root` argument takes precedence over
environment and ancestor discovery.

The injected context is derived only from:

```bash
python scripts/ts_workspace.py report_workspace --root <workspace>
```

It does not read or mutate ledger files directly. `report_workspace` remains the
only report source.

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
workspace state transitions, accepted-TS logic, Gaussian parsing, or backtrack
rules in TypeScript. Those contracts belong in Python modules and schemas.
