"""xTB backend adapter boundary."""

from __future__ import annotations

from transition_state_workflow.backends.base import FilesystemBackendAdapter


class XtbBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for xTB input generation and output parsing."""

    name = "xtb"
