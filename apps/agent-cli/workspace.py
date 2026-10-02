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

from tspi_runtime.workspace.cli import main


def _load_artifact_catalog(root: str | Path) -> dict[str, object]:
    """Load the optional scientific catalog only for ``context --mode locate``.

    Workspace context, validation, and change commands are dependency-neutral
    kernel operations.  Importing Compute at module load time pulled NumPy,
    RDKit, and their native extensions into every invocation (including
    ``--help``).  Keep the host adapter lazy so a file locator explicitly opts
    into the artifact catalog at the boundary where it is required.
    """

    from research_compute.artifacts import list_calculation_artifacts

    return list_calculation_artifacts(root)


if __name__ == "__main__":
    import sys

    if not sys.argv[1:] or sys.argv[1] != "allocate_operational_id":
        print(
            "the retired ResearchMap workspace CLI is unavailable; "
            "initialize workspaces with apps/agent-cli/workspace_mode.py",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(main(artifact_catalog_loader=_load_artifact_catalog))
