"""Contracts for ChemKernel workspace report packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping


DECISION_CONTEXT_SCHEMA = "ts-decision-context-v1"
PLAN_SCHEMA = DECISION_CONTEXT_SCHEMA
WorkspaceValidator = Callable[[Path], Mapping[str, Any]]
TsfreqEvidencePredicate = Callable[[Path, Mapping[str, object]], bool]


__all__ = [
    "PLAN_SCHEMA",
    "DECISION_CONTEXT_SCHEMA",
    "WorkspaceValidator",
    "TsfreqEvidencePredicate",
]
