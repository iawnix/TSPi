#!/usr/bin/env python3
"""Wrapper for the workspace control plane."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from ts_agent.workspace.cli import main


def _load_artifact_catalog(root: str | Path) -> dict[str, object]:
    """Load the optional scientific catalog only for ``context --mode locate``.

    Workspace context, validation, and change commands are dependency-neutral
    kernel operations.  Importing Compute at module load time pulled NumPy,
    RDKit, and their native extensions into every invocation (including
    ``--help``).  Keep the host adapter lazy so a file locator explicitly opts
    into the artifact catalog at the boundary where it is required.
    """

    from ts_agent.compute.artifacts import list_calculation_artifacts

    return list_calculation_artifacts(root)


if __name__ == "__main__":
    raise SystemExit(main(artifact_catalog_loader=_load_artifact_catalog))
