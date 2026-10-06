#!/usr/bin/env python3
"""Execution-plane ID allocator for an initialized canonical workspace.

Workspace creation is owned by ``workspace_mode.py``.  The retired
ResearchMap JSON/SQLite subcommands are intentionally unavailable so a
launcher cannot accidentally create a workspace from the old protocol.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from workspace_cli import main


if __name__ == "__main__":
    import sys

    if not sys.argv[1:] or sys.argv[1] != "allocate_operational_id":
        print(
            "the retired ResearchMap workspace CLI is unavailable; "
            "initialize workspaces with apps/agent-cli/workspace_mode.py",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(main())
