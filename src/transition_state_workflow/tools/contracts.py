"""Tool-neutral execution contracts for chemistry calculations and analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol


class ToolCapability(str, Enum):
    """Stable capability groups used for tool selection and registration."""

    CANDIDATE_GENERATION = "candidate_generation"
    OPTIMIZATION = "optimization"
    TSFREQ_VALIDATION = "tsfreq_validation"
    CONNECTIVITY_CHECK = "connectivity_check"
    DESCRIPTOR_ANALYSIS = "descriptor_analysis"


@dataclass(frozen=True)
class ToolRequest:
    """Node-scoped request passed to a ChemTool."""

    root_directory: Path
    node_id: str
    capability: ToolCapability
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Execution result containing evidence artifacts but no state mutation."""

    tool_name: str
    capability: ToolCapability
    ok: bool
    artifacts: tuple[Path, ...] = ()
    properties: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()


class ChemTool(Protocol):
    """Calculation or analysis tool that never writes scientific state."""

    name: str
    capabilities: frozenset[ToolCapability]

    def run(self, request: ToolRequest) -> ToolResult:
        """Run one node-scoped operation and return evidence-bearing artifacts."""
