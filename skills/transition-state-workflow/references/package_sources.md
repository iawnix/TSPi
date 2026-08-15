# Package Knowledge Sources

This policy separates public operating knowledge from package implementation.
It governs how the Root Agent learns to use TSPi; it does not prevent the host
from executing installed package code.

## Research Mode

Research mode is mandatory for versioned release installations and is the
default for terminal and Phone Root sessions. Use sources in this order:

1. Registered tool schemas and prompt guidelines define accepted call fields.
2. `ts_workspace_context mode=artifacts` and `mode=capabilities` provide live
   logical inputs and adapter support.
3. `SKILL.md`, focused `references/`, and public Skill assets explain operating
   semantics and scientific boundaries.

Do not inspect `tests/`, `src/`, `extensions/`, scripts, or backend/kernel
implementation to discover ordinary tool usage. Tests are regression evidence,
not examples for a research Agent.

The Root host blocks structured `read`, `grep`, `find`, and `ls` calls into
non-public package paths in research mode. This is a knowledge-routing guard,
not a filesystem security sandbox. Research workspace files remain readable.

## Maintenance Mode

Use maintenance mode only for an explicit request to diagnose, change, or
validate an authored TS package checkout. A release cannot be switched into
maintenance mode. Start the source launcher with an explicit development root:

```bash
TS_AGENT_INSTALL_ROOT=/path/to/TSPi-installation \
TS_PACKAGE_DEV_ROOT=/absolute/path/to/TSAgentSkill \
TS_PACKAGE_SOURCE_MODE=maintenance \
  /absolute/path/to/TSAgentSkill/TSPi --workspace <name>
```

Implementation and tests may then be inspected, but public calls must still be
derived from registered schemas and capabilities. Maintenance mode does not
relax workspace mutation, remote control, scientific Gate, or notification
contracts.

## Entry Points

- Terminal Root and Phone Root receive the same policy from the control
  extension. Phone policy only adds remote-interaction permissions.
- Compute, Review, Render, and Report children receive bounded task packets and
  request-scoped tools; they do not browse package sources.
- Deterministic CLIs and kernels execute typed data and do not consult these
  documentation files at runtime.
