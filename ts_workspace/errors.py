"""Workspace v5 error taxonomy."""


class ContractError(ValueError):
    """Raised when a v5 workspace contract cannot be satisfied."""


class WorkspaceValidationError(ContractError):
    """Raised when canonical state is internally inconsistent."""
