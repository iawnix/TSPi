"""ChemGate contract for evidence decisions and workspace validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from transition_state_workflow.base.contracts import GateDecision
from transition_state_workflow.base.findings import WorkspaceValidationFinding


class ChemGate(Protocol):
    """Read-only evaluator that never mutates scientific workspace state."""

    def evaluate_node(
        self,
        root_directory: Path,
        node_id: str,
        evidence: Sequence[Mapping[str, Any]],
    ) -> GateDecision:
        """Return the highest evidence-supported scientific claim."""

    def validate_workspace(self, root_directory: Path) -> tuple[WorkspaceValidationFinding, ...]:
        """Return all workspace consistency findings without modifying files."""

    def normalize_workspace(self, root_directory: Path) -> Mapping[str, Any]:
        """Return a derived read model for CLI and web consumers."""
