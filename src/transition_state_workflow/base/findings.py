"""Validation finding records shared by TS workflow tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceValidationFinding:
    """One validation finding with enough context for CLI and web rendering."""

    severity: str
    code: str
    message: str
    path: str = ""
    node_id: str = ""

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-serializable representation of this finding."""

        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "node_id": self.node_id,
        }

