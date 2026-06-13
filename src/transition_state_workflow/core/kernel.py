"""ChemKernel contract for planning nodes and writing scientific state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from transition_state_workflow.base.contracts import GateDecision, NodePlan


class ChemKernel(Protocol):
    """Single writer for tree, node, evidence, and pathway scientific state."""

    def plan_node(self, root_directory: Path, request: Mapping[str, Any]) -> NodePlan:
        """Build a chemistry-driven plan without running a calculation."""

    def create_node(self, plan: NodePlan) -> Mapping[str, Any]:
        """Create one planned node and update its workspace indexes."""

    def apply_gate_decision(
        self,
        root_directory: Path,
        decision: GateDecision,
    ) -> Mapping[str, Any]:
        """Apply a read-only gate decision through the canonical write path."""
