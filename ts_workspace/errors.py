"""Workspace v4 error taxonomy."""


class ContractError(ValueError):
    """Raised when a v4 workspace contract cannot be satisfied."""


class WorkspaceValidationError(ContractError):
    """Raised when canonical state is internally inconsistent."""
