"""Contracts for ChemKernel next-action planning packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping


PLAN_SCHEMA = "ts-next-action-plan-v1"
WorkspaceValidator = Callable[[Path], Mapping[str, Any]]
TsfreqEvidencePredicate = Callable[[Path, Mapping[str, object]], bool]


__all__ = [
    "PLAN_SCHEMA",
    "WorkspaceValidator",
    "TsfreqEvidencePredicate",
]
