"""Gaussian backend adapter boundary."""

from __future__ import annotations

from transition_state_workflow.backends.base import FilesystemBackendAdapter


class GaussianBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for Gaussian input generation and output parsing."""

    name = "gaussian"
