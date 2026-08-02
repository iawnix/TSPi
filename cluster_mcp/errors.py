"""Domain-specific exceptions returned by the MCP boundary."""


class ClusterMCPError(Exception):
    """Base class for expected cluster MCP errors."""


class ConfigurationError(ClusterMCPError):
    """Raised when configuration is invalid or incomplete."""


class SecurityError(ClusterMCPError):
    """Raised when an operation crosses a configured security boundary."""


class SchedulerError(ClusterMCPError):
    """Raised when the scheduler command fails or returns invalid data."""


class TransferError(ClusterMCPError):
    """Raised for invalid or incomplete file transfers."""
