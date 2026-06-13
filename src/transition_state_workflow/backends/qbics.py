"""QBICS backend adapter boundary."""

from __future__ import annotations

from transition_state_workflow.backends.base import FilesystemBackendAdapter


class QbicsBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for QBICS candidate-generation setup and parsing."""

    name = "qbics"
