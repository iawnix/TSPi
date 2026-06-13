"""Shared helpers for lightweight backend adapter scaffolds."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from transition_state_workflow.backends.contracts import BackendInput, BackendOutput


class FilesystemBackendAdapter:
    """Base adapter that records declared files and generic artifact metadata."""

    name: str

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Return backend input files from a backend-neutral request."""

        files = tuple(Path(item) for item in request.get("files", ()))
        command_argv = tuple(str(item) for item in request.get("command_argv", ()))
        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")
        return BackendInput(
            backend=self.name,
            files=files,
            command_argv=command_argv,
            metadata=metadata,
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Return generic artifact existence metadata."""

        return BackendOutput(
            backend=self.name,
            artifacts=artifacts,
            properties={
                "artifact_count": len(artifacts),
                "existing_artifacts": sum(1 for artifact in artifacts if artifact.exists()),
            },
        )
