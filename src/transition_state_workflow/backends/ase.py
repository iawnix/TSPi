"""ASE backend adapter boundary."""

from __future__ import annotations

from transition_state_workflow.backends.base import FilesystemBackendAdapter


class AseBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for ASE-managed calculation setup and parsing."""

    name = "ase"
