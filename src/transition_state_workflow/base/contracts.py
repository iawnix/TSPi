"""Stable data contracts shared by workflow architecture layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class NodePlan:
    """Chemistry-driven plan for one new workflow node."""

    root_directory: Path
    node_id: str
    parent_id: str | None
    stage: str
    operation: str
    hypothesis: str
    changed_variables: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateDecision:
    """Read-only scientific decision produced by a gate for kernel application."""

    node_id: str
    claim_status: str
    outcome: str
    outcome_code: str | None = None
    evidence_gates: Mapping[str, bool] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
