"""Shared error type for the NEB toolkit."""

from __future__ import annotations


class ConfigError(ValueError):
    """Raised when a NEB config is invalid."""
