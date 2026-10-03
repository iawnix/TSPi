"""Errors for the canonical Research State boundary."""


class ContractError(ValueError):
    """A state or workspace contract is invalid."""


class WorkspaceValidationError(ContractError):
    """A canonical workspace does not satisfy the State contract."""
