#!/usr/bin/env python3
"""Wrapper for the workspace control plane."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from ts_agent.workspace.cli import main
from ts_agent.compute.artifacts import list_calculation_artifacts


if __name__ == "__main__":
    raise SystemExit(main(artifact_catalog_loader=list_calculation_artifacts))
