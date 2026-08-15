# Package Knowledge Sources

This policy separates public operating knowledge from package implementation.
It governs how the Root Agent learns to use TSPi; it does not prevent the host
from executing installed package code.

## Research Runtime

Terminal and Phone Root sessions always run a versioned installed release. Use
knowledge sources in this order:

1. Registered tool schemas and prompt guidelines define accepted call fields.
2. `ts_workspace_context mode=artifacts` and `mode=capabilities` provide live
   logical inputs and adapter support.
3. `SKILL.md`, focused `references/`, and public Skill assets explain operating
   semantics and scientific boundaries.

Do not inspect `tests/`, `src/`, `extensions/`, scripts, or backend/kernel
implementation to discover ordinary tool usage. Tests are regression evidence,
not examples for a research Agent.

The Root host blocks structured `read`, `grep`, `find`, and `ls` calls into
non-public package paths. This is a knowledge-routing guard, not a filesystem
security sandbox. Research workspace files remain readable.

## Package Maintenance

Diagnose, change, and validate package implementation in the separate authored
checkout, not inside a research TSPi session. After tests pass, build and
install a versioned release:

```bash
cd /absolute/path/to/TSAgentSkill
python3 scripts/check_package.py
python3 scripts/build_release.py --output-dir dist --json
python3 scripts/install_release.py \
  --manifest dist/ts-agent-release.json \
  --install-root /path/to/TSPi-installation \
  --json
```

The next TSPi process resolves the newly selected `current` release. Existing
processes keep the release they started with. Installation never relaxes
workspace mutation, remote control, scientific Gate, or notification contracts.

## Entry Points

- Terminal Root and Phone Root receive the same policy from the control
  extension. Phone policy only adds remote-interaction permissions.
- Compute, Review, Render, and Report children receive bounded task packets and
  request-scoped tools; they do not browse package sources.
- Deterministic CLIs and kernels execute typed data and do not consult these
  documentation files at runtime.
