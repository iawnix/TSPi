"""Workspace error taxonomy."""


class ContractError(ValueError):
    """Raised when a workspace contract cannot be satisfied."""


class WorkspaceValidationError(ContractError):
    """Raised when canonical state is internally inconsistent."""
