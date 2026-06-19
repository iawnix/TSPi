"""Contracts for ChemKernel workspace report packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

WORKSPACE_REPORT_PACKET_SCHEMA = "ts-workspace-report-packet"
WorkspaceValidator = Callable[[Path], Mapping[str, Any]]
TsfreqEvidencePredicate = Callable[[Path, Mapping[str, object]], bool]


__all__ = [
    "WORKSPACE_REPORT_PACKET_SCHEMA",
    "WorkspaceValidator",
    "TsfreqEvidencePredicate",
]
